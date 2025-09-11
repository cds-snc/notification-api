#!/bin/sh
if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
    echo "ENTRY.SH: Running locally"
    exec /usr/bin/aws-lambda-rie $(which python) -m awslambdaric $1
else
    . /sync_lambda_envs.sh
    VAR_NAMES=$(env | cut -d '=' -f 1 | sort)
    echo "ENTRY.SH: Running in AWS Lambda (. /sync_lambda_envs.sh script)
All environment variable names (from AWS Parameter Store):
${VAR_NAMES}"
    exec $(which python) -m awslambdaric $1
fi
