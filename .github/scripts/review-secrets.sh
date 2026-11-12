#!/usr/bin/env bash
set -euo pipefail
umask 077

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
baseline="$root/.github/trufflehog-baseline.json"
if [[ "${GITHUB_ACTIONS:-false}" == true ]]; then
  echo "Secret review is local-only: source context may expose credentials." >&2
  exit 1
fi
if [[ $# != 1 || ! -f "$1/hashed.jsonl" ]]; then
  echo "Usage: bash .github/scripts/review-secrets.sh SCAN_OUTPUT_DIRECTORY" >&2
  echo "The directory must contain hashed.jsonl from a retained successful scan." >&2
  exit 1
fi

lock="$baseline.review-lock"
if ! mkdir "$lock"; then
  echo "Another review may be running. Resolve $lock before retrying." >&2
  exit 1
fi
temporary=""
cleanup() {
  rm -f "$lock/findings.json" "$lock/source" "$lock/original.json"
  if [[ -n "$temporary" ]]; then rm -f "$temporary"; fi
  rmdir "$lock"
}
trap cleanup EXIT
cp "$baseline" "$lock/original.json"

if ! jq -e '
  type == "array" and all(.[];
    ([.detector, .commit, .file, .reason] | all(type == "string" and length > 0)) and
    (.raw_sha256 | type == "string" and test("^[0-9a-f]{64}$"))
  )
' "$baseline" > /dev/null; then
  echo "Invalid baseline; review aborted." >&2
  exit 1
fi
if ! jq -se '
  if all(.[];
    ([.DetectorName, .SourceMetadata.Data.Git.file] | all(type == "string" and length > 0)) and
    (.SourceMetadata.Data.Git.commit | type == "string" and test("^[0-9a-f]{40}$")) and
    (.SourceMetadata.Data.Git.line | type == "number" and . > 0 and floor == .) and
    (.RawSHA256 | type == "string" and test("^[0-9a-f]{64}$")) and
    (.Verified | type == "boolean")
  ) then . else error("Invalid finding metadata") end
' "$1/hashed.jsonl" > "$lock/findings.json"; then
  echo "Invalid retained findings; review aborted." >&2
  exit 1
fi

echo "WARNING: historical source may contain credentials. Do not record or share this terminal."
echo "Only reviewed non-secrets or confirmed revoked exposures may be approved."
total=$(jq length "$lock/findings.json")
saved=0
skipped=0
for ((index = 0; index < total; index++)); do
  finding=$(jq -c --argjson index "$index" '.[$index]' "$lock/findings.json")
  if jq -e --argjson finding "$finding" '
    any(.[];
      $finding.Verified == false and
      .detector == $finding.DetectorName and
      (.commit == "*" or .commit == $finding.SourceMetadata.Data.Git.commit) and
      .file == $finding.SourceMetadata.Data.Git.file and
      .raw_sha256 == $finding.RawSHA256
    )
  ' "$baseline" > /dev/null; then
    printf 'Finding %s/%s already baselined; skipping.\n' "$((index + 1))" "$total"
    continue
  fi

  printf '\nFinding %s/%s\n' "$((index + 1))" "$total"
  printf '%s\n' "$finding" | jq '{detector: .DetectorName, verified: .Verified, location: .SourceMetadata.Data.Git}'
  commit=$(printf '%s\n' "$finding" | jq -r '.SourceMetadata.Data.Git.commit')
  file=$(printf '%s\n' "$finding" | jq -r '.SourceMetadata.Data.Git.file')
  line=$(printf '%s\n' "$finding" | jq -r '.SourceMetadata.Data.Git.line')
  if ! git -C "$root" show "${commit}:${file}" > "$lock/source"; then
    echo "Unable to load historical source; review aborted without approving this finding." >&2
    exit 1
  fi
  if ! node - "$lock/source" "$line" <<'JS'
const fs = require('node:fs');
const bytes = fs.readFileSync(process.argv[2]);
if (bytes.includes(0)) {
  console.error('Binary source cannot be displayed; review it privately before approving.');
  process.exit(1);
}
const lines = bytes.toString('utf8').split('\n');
const line = Number(process.argv[3]);
if (line > lines.length) {
  console.error('Finding line is outside historical source.');
  process.exit(1);
}
for (let i = Math.max(0, line - 6); i < Math.min(lines.length, line + 5); i++) {
  const safe = lines[i].replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f]/g,
    char => `\\x${char.charCodeAt(0).toString(16).padStart(2, '0')}`);
  console.log(`${i + 1 === line ? '>' : ' '} ${i + 1}\t${safe}`);
}
JS
  then
    echo "Context unavailable. This finding will remain unbaselined." >&2
    skipped=$((skipped + 1))
    read -r -p "Enter to continue, q to quit: " choice || break
    if [[ "$choice" == q ]]; then break; fi
    continue
  fi

  while true; do
    read -r -p "[a] Approve non-secret, [r] Confirm revoked exposure, [s/Enter] Skip, [q] Quit: " choice || choice=q
    case "$choice" in
      q) break 2 ;;
      s|"") skipped=$((skipped + 1)); break ;;
      a|r)
        if [[ $(printf '%s\n' "$finding" | jq -r '.Verified') != false ]]; then
          echo "Verified findings cannot be suppressed by this baseline. Skip and investigate." >&2
          continue
        fi
        read -r -p "Reason (do not include detected values): " reason || break 2
        if [[ ! "$reason" =~ [^[:space:]] ]]; then
          echo "A nonempty reason is required." >&2
          continue
        fi
        if [[ "$choice" == r ]]; then
          read -r -p "Who confirmed revocation: " reviewer || break 2
          read -r -p "Revocation confirmation date (YYYY-MM-DD): " date || break 2
          if [[ ! "$reviewer" =~ [^[:space:]] || ! "$date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
            echo "Reviewer and confirmation date are required." >&2
            continue
          fi
          reason="Revoked historical exposure; revocation confirmed by $reviewer on $date. $reason"
        else
          reason="Reviewed non-secret. $reason"
        fi
        temporary=$(mktemp "$baseline.XXXXXX")
        jq --argjson finding "$finding" --arg reason "$reason" '
          . + [{
            detector: $finding.DetectorName,
            commit: $finding.SourceMetadata.Data.Git.commit,
            file: $finding.SourceMetadata.Data.Git.file,
            raw_sha256: $finding.RawSHA256,
            reason: $reason
          }]
        ' "$baseline" > "$temporary"
        if ! cmp -s "$baseline" "$lock/original.json"; then
          echo "Baseline changed outside this review; refusing to overwrite it." >&2
          exit 1
        fi
        mv "$temporary" "$baseline"
        temporary=""
        cp "$baseline" "$lock/original.json"
        saved=$((saved + 1))
        echo "Saved exact-commit exception. Moving to the next finding."
        break
        ;;
      *) echo "Choose a, r, s, or q." >&2 ;;
    esac
  done
done
printf '\nReview finished: %s approvals saved, %s findings skipped.\n' "$saved" "$skipped"
echo "Re-run bash .github/scripts/scan-secrets.sh --native to reconcile the updated baseline."
