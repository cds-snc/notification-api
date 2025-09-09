#!/bin/sh
if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
    echo "ENTRY.SH: Running locally"
    exec /usr/bin/aws-lambda-rie $(which python) -m awslambdaric $1
else
    . /sync_lambda_envs.sh
    # Collect environment variable names (sorted) into a JSON array for a single CloudWatch structured log line
    VAR_NAMES_NL=$(env | cut -d '=' -f 1 | sort)
    ENV_VAR_COUNT=$(printf '%s\n' "$VAR_NAMES_NL" | grep -c '^')
    # Build JSON array manually (avoid requiring jq at runtime)
    VAR_NAMES_JSON=$(printf '%s\n' "$VAR_NAMES_NL" | awk 'BEGIN { printf("["); first=1 } { gsub(/"/, "\\\""); if(!first) printf(","); printf("\"%s\"", $0); first=0 } END { printf("]") }')
    TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u)
    # Single structured JSON line
    echo "{\"timestamp\":\"$TS\",\"source\":\"entry.sh\",\"mode\":\"lambda\",\"loader\":\"sync_lambda_envs.sh\",\"new_relic_enabled\":\"${NEW_RELIC_ENABLED:-unset}\",\"env_var_count\":$ENV_VAR_COUNT,\"env_var_names\":$VAR_NAMES_JSON}"
    exec $(which python) -m awslambdaric $1
fi