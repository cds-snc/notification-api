#!/bin/sh
if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
    RUNTIME_CMD="/usr/bin/aws-lambda-rie $(which python)"
else
    . /sync_lambda_envs.sh # Retrieve .env from parameter store and remove currently set environement variables
    RUNTIME_CMD="$(which python)"
fi

exec ${RUNTIME_CMD} -m awslambdaric $1