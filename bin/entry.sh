#!/bin/sh

RESOLVED_HANDLER="$1"
if [ -z "$RESOLVED_HANDLER" ] || [ "$RESOLVED_HANDLER" = "\${APP_HANDLER}" ]; then
  RESOLVED_HANDLER="${APP_HANDLER:-application.handler}"
fi

if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
    echo "ENTRY.SH: Running locally (handler=${RESOLVED_HANDLER})"
    exec /usr/bin/aws-lambda-rie $(which python) -m awslambdaric "$RESOLVED_HANDLER"
else
    . /sync_lambda_envs.sh
    # Collect environment variable names (sorted)
    VAR_NAMES_NL=$(env | cut -d '=' -f 1 | sort)
    ENV_VAR_COUNT=$(printf '%s\n' "$VAR_NAMES_NL" | grep -c '^')
    # Build JSON array using jo (each line becomes a string element)
    VAR_NAMES_JSON=$(printf '%s\n' "$VAR_NAMES_NL" | jo -a)
    TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u)
    # Construct final JSON object with jo (include resolved handler)
    FINAL_JSON=$(jo \
        timestamp="$TS" \
        source="entry.sh" \
        mode="lambda" \
        loader="sync_lambda_envs.sh" \
        handler="$RESOLVED_HANDLER" \
        env_var_count="$ENV_VAR_COUNT" \
        env_var_names="$(printf '%s' "$VAR_NAMES_JSON")" \
    )
    echo "$FINAL_JSON"
    exec $(which python) -m awslambdaric "$RESOLVED_HANDLER"
fi