#!/bin/sh
if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
    RUNTIME_CMD="/usr/bin/aws-lambda-rie $(which python)"
else
    . /sync_lambda_envs.sh # Retrieve .env from parameter store and remove currently set environement variables
    RUNTIME_CMD="$(which python)"
fi

## IMPORTANT: NEW RELIC CONFIGURATION -- WE ALWAYS WANT TO USE APM MODE!
# Force classic New Relic agent mode for Lambda so data flows to APM instead of the serverless extension
unset NEW_RELIC_LAMBDA_EXTENSION_ENABLED
unset NEW_RELIC_LAMBDA_HANDLER
unset NEW_RELIC_EXTENSION_LOGS_ENABLED
unset NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS
export NEW_RELIC_SERVERLESS_MODE_ENABLED=false
NEW_RELIC_CONFIG_FILE=${NEW_RELIC_CONFIG_FILE:-/app/newrelic.ini}
export NEW_RELIC_CONFIG_FILE

exec ${RUNTIME_CMD} -m awslambdaric $1