#!/bin/sh
if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
    echo "ENTRY.SH: Running locally"
    exec /usr/bin/aws-lambda-rie $(which python) -m awslambdaric $1
else
    echo "ENTRY.SH: Running in AWS Lambda"
    . /sync_lambda_envs.sh
    env  # Optional: dump all environment variables
    exec $(which python) -m awslambdaric $1
fi