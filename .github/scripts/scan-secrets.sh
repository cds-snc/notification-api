#!/usr/bin/env bash
set -euo pipefail
umask 077

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
native=false
output=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --native) native=true; shift ;;
    --output-dir)
      if [[ $# -lt 2 || -z "$2" ]]; then
        echo "--output-dir requires a new directory path." >&2
        exit 1
      fi
      output=$2
      shift 2
      ;;
    *)
      echo "Usage: bash .github/scripts/scan-secrets.sh [--native] [--output-dir NEW_DIRECTORY]" >&2
      exit 1
      ;;
  esac
done

if [[ "${GITHUB_ACTIONS:-false}" == "true" && ( "$native" == true || -n "$output" ) ]]; then
  echo "Native scanning and retained raw output are local-only options." >&2
  exit 1
fi

if [[ -n "$output" ]]; then
  mkdir -m 700 "$output"
  temporary=$(cd "$output" && pwd)
  echo "WARNING: private raw findings and diagnostic logs will be retained in $temporary. Do not commit or share these files." >&2
else
  temporary=$(mktemp -d)
  trap 'rm -f "$temporary/results.jsonl" "$temporary/errors.log" "$temporary/report.json" "$temporary/validation.log" "$temporary/hashed.jsonl"; rmdir "$temporary"' EXIT
fi

base=""
head=""
case "${GITHUB_EVENT_NAME:-local}" in
  pull_request)
    base=$(jq -er '.pull_request.base.sha' "$GITHUB_EVENT_PATH")
    head=$(jq -er '.pull_request.head.sha' "$GITHUB_EVENT_PATH")
    ;;
  push)
    base=$(jq -er '.before' "$GITHUB_EVENT_PATH")
    head=$(jq -er '.after' "$GITHUB_EVENT_PATH")
    if [[ "$base" == "0000000000000000000000000000000000000000" ]]; then
      base=""
    fi
    ;;
  workflow_dispatch|schedule|local) ;;
  *)
    echo "Unsupported secret scanning event: ${GITHUB_EVENT_NAME}" >&2
    exit 1
    ;;
esac

if [[ -n "$base" && "$base" == "$head" ]]; then
  echo "Secret scanning base and head must differ." >&2
  exit 1
fi

arguments=(--json --log-level=2 --no-verification --no-update --fail-on-scan-errors)
if [[ -n "$head" ]]; then
  arguments+=(--branch "$head")
fi
if [[ -n "$base" ]]; then
  arguments+=(--since-commit "$base")
fi

echo "Event: ${GITHUB_EVENT_NAME:-local}; scanner: 3.99.7."
echo "Scanning ${head:-all available refs}, starting after ${base:-the beginning of history}."
echo "All-ref results depend on the branches and tags available in this checkout."
# Findings are evaluated below, not with --fail, so scan errors cannot be
# mistaken for an exit caused only by baselined findings.
if [[ "$native" == true ]]; then
  version=$(trufflehog --version 2>&1)
  echo "Installed scanner: $version"
  command=(trufflehog git "file://$root")
else
  # v3.99.7 multi-platform manifest (linux/amd64 and linux/arm64).
  command=(docker run --rm -v "$root:/repo:ro" ghcr.io/trufflesecurity/trufflehog@sha256:0d003fc3abc4e1565eca8462b992001314de51451e96e3c44de80d116794d5d1 git file:///repo)
fi
if "${command[@]}" "${arguments[@]}" > "$temporary/results.jsonl" 2> "$temporary/errors.log"; then
  :
else
  status=$?
  echo "TruffleHog failed with exit code $status; findings were not accepted. Raw output is withheld because it may contain credentials." >&2
  exit "$status"
fi

if ! node - "$temporary/results.jsonl" > "$temporary/hashed.jsonl" 2> "$temporary/validation.log" <<'JS'
const fs = require('node:fs');
const crypto = require('node:crypto');
for (const line of fs.readFileSync(process.argv[2], 'utf8').split('\n')) {
  if (!line.trim()) continue;
  const finding = JSON.parse(line);
  if (typeof finding.Raw !== 'string' || finding.Raw.length === 0) {
    throw new Error('Missing detected value');
  }
  finding.RawSHA256 = crypto.createHash('sha256').update(finding.Raw).digest('hex');
  delete finding.Raw;
  console.log(JSON.stringify(finding));
}
JS
then
  echo "Unable to hash TruffleHog results; scan failed. Raw output is withheld because it may contain credentials." >&2
  exit 1
fi

if ! jq -s --slurpfile baseline "$root/.github/trufflehog-baseline.json" '
  def nonempty_string: type == "string" and length > 0;
  if ($baseline | length) != 1 or ($baseline[0] | type) != "array" then
    error("Invalid baseline")
  elif any($baseline[0][];
    (([.detector, .commit, .file, .raw_sha256, .reason] | all(nonempty_string)) and
      (.raw_sha256 | test("^[0-9a-f]{64}$"))) | not
  ) then
    error("Invalid baseline entry")
  elif any(.[];
    ([.DetectorName, .RawSHA256, .SourceMetadata.Data.Git.commit, .SourceMetadata.Data.Git.file]
      | all(nonempty_string)) | not
  ) then
    error("Invalid finding")
  else
    . as $findings |
    [.[] |
      . as $finding |
      [$baseline[0][] | select(
        $finding.Verified == false and
        $finding.DetectorName == .detector and
        (.commit == "*" or $finding.SourceMetadata.Data.Git.commit == .commit) and
        $finding.SourceMetadata.Data.Git.file == .file and
        $finding.RawSHA256 == .raw_sha256
      )] as $matches |
      {
        detector: .DetectorName,
        detector_version: .DetectorVersion,
        decoder: .DecoderName,
        verified: .Verified,
        commit: .SourceMetadata.Data.Git.commit,
        file: .SourceMetadata.Data.Git.file,
        line: .SourceMetadata.Data.Git.line,
        timestamp: .SourceMetadata.Data.Git.timestamp,
        baselined: ($matches | length > 0),
        reason: ($matches[0].reason // null)
      }
    ] as $details |
    {
      total: ($findings | length),
      baselined: ([$details[] | select(.baselined)] | length),
      details: $details,
      findings: [$details[] | select(.baselined | not)]
    }
  end
' "$temporary/hashed.jsonl" > "$temporary/report.json" 2> "$temporary/validation.log"; then
  echo "Unable to validate TruffleHog results or baseline; scan failed. Raw output is withheld because it may contain credentials." >&2
  exit 1
fi

echo "Every finding, including baseline matches (detected values omitted):"
jq -c '.details | to_entries[] | {finding: (.key + 1)} + .value' "$temporary/report.json"
echo "Scan metrics (when supplied by TruffleHog):"
jq -Rc 'fromjson? | select(.msg == "finished scanning") |
  {chunks, bytes, verified_secrets, unverified_secrets, scan_duration, trufflehog_version}' \
  "$temporary/errors.log"
jq '{total, baselined, remaining: (.findings | length)}' "$temporary/report.json"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  jq -r '"### TruffleHog\n\nFindings: \(.total)\n\nReviewed baseline exceptions: \(.baselined)\n\nRemaining findings: \(.findings | length)"' \
    "$temporary/report.json" >> "$GITHUB_STEP_SUMMARY"
fi

if jq -e '.findings | length > 0' "$temporary/report.json" > /dev/null; then
  echo "Unbaselined findings (detected values omitted):" >&2
  jq -c '.findings[]' "$temporary/report.json"
  exit 1
fi
