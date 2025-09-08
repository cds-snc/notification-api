#!/bin/sh
if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
    echo "ENTRY.SH: Running locally"
    exec /usr/bin/aws-lambda-rie $(which python) -m awslambdaric $1
else
    echo "ENTRY.SH: Running in AWS Lambda"
    . /sync_lambda_envs.sh
    echo "All environment variable names:"
    env | cut -d '=' -f 1
    exec $(which python) -m awslambdaric $1
fi