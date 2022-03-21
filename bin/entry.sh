#!/bin/sh
if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
    aws ssm get-parameters --region ca-central-1 --with-decryption --names ENVIRONMENT_VARIABLES --query 'Parameters[*].Value' --output text > "${TASK_ROOT}/.env"
    exec /usr/bin/aws-lambda-rie /usr/local/bin/python -m awslambdaric $1
else
    exec /usr/local/bin/python -m awslambdaric $1
fi