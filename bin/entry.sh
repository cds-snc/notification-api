#!/bin/sh

APP_HANDLER="${1:-application.handler}"

if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
    echo "ENTRY.SH: Running locally (app_handler=${APP_HANDLER})"
    exec /usr/bin/aws-lambda-rie $(which python) -m awslambdaric "$APP_HANDLER"
else
    . /sync_lambda_envs.sh
    # Collect environment variable names (sorted)
    VAR_NAMES_NL=$(env | cut -d '=' -f 1 | sort)
    ENV_VAR_COUNT=$(printf '%s\n' "$VAR_NAMES_NL" | grep -c '^')
    # Build JSON array using jo (each line becomes a string element)
    VAR_NAMES_JSON=$(printf '%s\n' "$VAR_NAMES_NL" | jo -a)
    TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u)
    # Construct final JSON object with jo
    FINAL_JSON=$(jo \
        timestamp="$TS" \
        source="entry.sh" \
        mode="lambda" \
        loader="sync_lambda_envs.sh" \
        app_handler="$APP_HANDLER" \
        env_var_count="$ENV_VAR_COUNT" \
        env_var_names="$(printf '%s' "$VAR_NAMES_JSON")" \
    )
    echo "$FINAL_JSON"
    exec $(which python) -m awslambdaric "$APP_HANDLER"
fi