#!/bin/bash
# run_failure_scenarios.sh
#
# Runs 5 blast_api.py scenarios in sequence. Each test ramps or spikes load
# until the error rate exceeds ERROR_THRESHOLD, at which point blast_api.py
# stops the test automatically. A configurable cool-down follows before the
# next scenario begins.
#
# Scenarios:
#   1. Gradual ramp-up of individual sends until system failure
#   2. Spike of individual sends until system failure  (SPIKE_USERS configurable)
#   3. Gradual ramp-up of bulk sends until system failure
#   4. Spike of bulk sends until system failure        (SPIKE_USERS configurable)
#   5. Gradual ramp-up of GET requests only until system failure
#
# Environment variables (all optional — defaults shown):
#   COOLDOWN          Cool-down between scenarios in seconds      (default: 1800 / 30 min)
#   ERROR_THRESHOLD   Error % that stops each test                (default: 3.0)
#   MIN_REQUESTS      Requests before threshold is evaluated      (default: 100)
#   SPIKE_USERS       Concurrent users for spike scenarios 2 & 4  (default: 500)
#   OUTPUT_DIR        Directory for CSV/HTML results              (default: /tmp/blast_scenarios/<timestamp>)
#   PERF_TEST_AWS_S3_BUCKET  S3 bucket to upload results to      (default: notify-performance-test-results-staging)
#
# Usage:
#   cd tests_nightly_performance
#   ./run_failure_scenarios.sh
#
#   SPIKE_USERS=1000 COOLDOWN=600 ./run_failure_scenarios.sh

set -uo pipefail

# ---------------------------------------------------------------------------
# Configurable defaults
# ---------------------------------------------------------------------------
COOLDOWN="${COOLDOWN:-1800}"
ERROR_THRESHOLD="${ERROR_THRESHOLD:-3.0}"
MIN_REQUESTS="${MIN_REQUESTS:-100}"
SPIKE_USERS="${SPIKE_USERS:-500}"
PERF_TEST_AWS_S3_BUCKET="${PERF_TEST_AWS_S3_BUCKET:-notify-performance-test-results-staging}"

current_time=$(date "+%Y.%m.%d-%H.%M.%S")
OUTPUT_DIR="${OUTPUT_DIR:-/tmp/blast_scenarios/$current_time}"
S3_BASE="s3://${PERF_TEST_AWS_S3_BUCKET}/redline_perf_tests/${current_time}"

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

mkdir -p "$OUTPUT_DIR"

# Base locust invocation — overrides run-time from locust.conf so each test
# runs until the error threshold (or manual interrupt), not a fixed duration.
LOCUST_BASE=(
    locust
    --config locust.conf
    --locustfile src/blast_api.py
    --run-time 1h
    --error-threshold "$ERROR_THRESHOLD"
    --min-requests "$MIN_REQUESTS"
    --wait-min 0
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { echo "[$(date '+%H:%M:%S')] $*"; }

run_scenario() {
    local number="$1"
    local slug="$2"
    local label="$3"
    shift 3
    local extra_flags=("$@")

    log "========================================================"
    log "Scenario $number: $label"
    log "========================================================"

    "${LOCUST_BASE[@]}" \
        "${extra_flags[@]}" \
        --csv  "$OUTPUT_DIR/${slug}" \
        --html "$OUTPUT_DIR/${slug}.html" \
        || true   # don't abort the suite if locust exits non-zero

    log "Scenario $number complete. Uploading results to S3..."
    aws s3 cp "$OUTPUT_DIR/" "${S3_BASE}/${slug}/" --recursive --exclude "*" \
        --include "${slug}*" || log "WARNING: S3 upload failed for scenario $number"
}

cooldown() {
    local next="$1"
    log "Cooling down for ${COOLDOWN}s before scenario $next... (Ctrl-C to skip cool-down)"
    sleep "$COOLDOWN" &
    local sleep_pid=$!
    # Trap SIGINT so Ctrl-C only kills the sleep, not the whole script.
    trap "kill $sleep_pid 2>/dev/null; log 'Cool-down skipped.'" INT
    wait $sleep_pid
    trap - INT  # restore default SIGINT handling for the next scenario
}

# ---------------------------------------------------------------------------
# Print summary
# ---------------------------------------------------------------------------
log "========================================================"
log "Blast API Failure Scenario Suite"
log "Output directory : $OUTPUT_DIR"
log "S3 destination   : ${S3_BASE}/<scenario>/"
log "Error threshold  : ${ERROR_THRESHOLD}%  (min requests: $MIN_REQUESTS)"
log "Spike user count : $SPIKE_USERS"
log "Cool-down        : ${COOLDOWN}s between scenarios"
log "========================================================"
echo ""

# ---------------------------------------------------------------------------
# Scenario 1 — Gradual ramp-up of individual sends
#   Starts at 10 users, steps up by 50 every 120 s until error threshold.
# ---------------------------------------------------------------------------
run_scenario 1 "individual-send-ramp-up" "Gradual ramp-up of individual sends" \
    --skip-bulk \
    --start-users 10

cooldown 2

# ---------------------------------------------------------------------------
# Scenario 2 — Spike of individual sends  (SPIKE_USERS configurable)
#   Immediately holds SPIKE_USERS concurrent users until error threshold.
# ---------------------------------------------------------------------------
run_scenario 2 "individual-send-spike" "Spike of individual sends (${SPIKE_USERS} users)" \
    --skip-bulk \
    --constant-users "$SPIKE_USERS"

cooldown 3

# ---------------------------------------------------------------------------
# Scenario 3 — Gradual ramp-up of bulk sends
#   Starts at 10 users, steps up by 50 every 120 s until error threshold.
# ---------------------------------------------------------------------------
run_scenario 3 "bulk-send-ramp-up" "Gradual ramp-up of bulk sends" \
    --bulk-only \
    --start-users 10

cooldown 4

# ---------------------------------------------------------------------------
# Scenario 4 — Spike of bulk sends  (SPIKE_USERS configurable)
#   Immediately holds SPIKE_USERS concurrent users until error threshold.
# ---------------------------------------------------------------------------
run_scenario 4 "bulk-send-spike" "Spike of bulk sends (${SPIKE_USERS} users)" \
    --bulk-only \
    --constant-users "$SPIKE_USERS"

cooldown 5

# ---------------------------------------------------------------------------
# Scenario 5 — Gradual ramp-up of GET requests only
#   Starts at 10 users, steps up by 50 every 120 s until error threshold.
# ---------------------------------------------------------------------------
run_scenario 5 "get-ramp-up" "Gradual ramp-up of GET requests only" \
    --get-only \
    --start-users 10

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
log "========================================================"
log "All scenarios complete."
log "Results: $OUTPUT_DIR"
log "S3 path : ${S3_BASE}/"
log "========================================================"
