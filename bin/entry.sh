#!/bin/sh

# Minimal Lambda entrypoint: runs RIE locally, awslambdaric in Lambda.
# No environment dumping (SSM vars load later inside Python).

if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
    exec /usr/bin/aws-lambda-rie $(which python) -m awslambdaric "$1"
else
    exec $(which python) -m awslambdaric "$1"
fi