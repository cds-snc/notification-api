#!/bin/sh
if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
    exec /usr/bin/aws-lambda-rie $(which python) -m awslambdaric $1
else
    . /sync_lambda_envs.sh # Retrieve .env from parameter store and remove currently set environement variables
    exec $(which python) -m awslambdaric $1
fi