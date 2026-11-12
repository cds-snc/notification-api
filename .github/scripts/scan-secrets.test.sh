#!/usr/bin/env bash
set -euo pipefail
umask 077

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
mkdir -p "$temporary/repo/.github/scripts" "$temporary/repo/.github" "$temporary/bin"
cp "$root/.github/scripts/scan-secrets.sh" "$temporary/repo/.github/scripts/"
cp "$root/.github/trufflehog-baseline.json" "$temporary/repo/.github/"

export FIXTURE="$temporary/results.jsonl"
export ARGUMENTS="$temporary/arguments"
export GITHUB_EVENT_PATH="$temporary/event.json"
export GITHUB_EVENT_NAME=push
export GITHUB_ACTIONS=false
export PATH="$temporary/bin:$PATH"
printf '%s\n' '{"before":"before-commit","after":"after-commit"}' > "$GITHUB_EVENT_PATH"

cat > "$temporary/bin/docker" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$ARGUMENTS"
cat "$FIXTURE"
echo '{"msg":"finished scanning","chunks":1,"bytes":2,"trufflehog_version":"3.99.7"}' >&2
exit "${SCANNER_EXIT:-0}"
SH
chmod +x "$temporary/bin/docker"

check() {
  local expected=$1
  local name=$2
  local status=0
  bash "$temporary/repo/.github/scripts/scan-secrets.sh" > "$temporary/output" 2>&1 || status=$?
  if [[ "$status" != "$expected" ]]; then
    echo "FAIL: $name (expected exit $expected, got $status)" >&2
    cat "$temporary/output" >&2
    exit 1
  fi
  if grep -q 'TEST_ONLY_REDACTED_FIXTURE' "$temporary/output"; then
    echo "FAIL: detected value leaked to output" >&2
    exit 1
  fi
  echo "PASS: $name"
}

: > "$FIXTURE"
check 0 "clean scan"
grep -qx 'before-commit' "$ARGUMENTS"
grep -qx 'after-commit' "$ARGUMENTS"
grep -qx 'ghcr.io/trufflesecurity/trufflehog@sha256:0d003fc3abc4e1565eca8462b992001314de51451e96e3c44de80d116794d5d1' "$ARGUMENTS"

GITHUB_EVENT_NAME=workflow_call check 0 "reusable workflow scans all refs"
if grep -qxE -- '--since-commit|--branch' "$ARGUMENTS"; then
  echo "FAIL: reusable workflow scan must include all available refs" >&2
  exit 1
fi

finding='{
  "DetectorName": "SyntheticTestDetector",
  "Verified": false,
  "Raw": "TEST_ONLY_REDACTED_FIXTURE",
  "SourceMetadata": {"Data": {"Git": {
    "commit": "finding-commit",
    "file": "fixture.txt",
    "line": 1
  }}}
}'
finding=$(printf '%s\n' "$finding" | jq -c .)
hash=$(printf '%s' 'TEST_ONLY_REDACTED_FIXTURE' | node -e '
  const crypto = require("node:crypto");
  const fs = require("node:fs");
  console.log(crypto.createHash("sha256").update(fs.readFileSync(0)).digest("hex"));
')
printf '%s\n' "$finding" > "$FIXTURE"

jq -n --arg hash "$hash" '[
  {
    detector: "SyntheticTestDetector",
    commit: "finding-commit",
    file: "fixture.txt",
    raw_sha256: $hash,
    reason: "Synthetic test finding."
  }
]' > "$temporary/repo/.github/trufflehog-baseline.json"
check 0 "exact baseline match"
grep -q '"baselined":true' "$temporary/output"

jq '.[0].raw_sha256 = ("0" * 64)' "$temporary/repo/.github/trufflehog-baseline.json" \
  > "$temporary/modified-baseline.json"
mv "$temporary/modified-baseline.json" "$temporary/repo/.github/trufflehog-baseline.json"
check 1 "changed value is not baselined"

SCANNER_EXIT=125 check 125 "scanner failure propagated"

echo "Secret scanning tests passed."
