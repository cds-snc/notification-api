#!/bin/bash

# a workaround for datadog agent under-reporting statsd metrics on ecs fargate
# taken from https://github.com/DataDog/datadog-agent/issues/3159#issuecomment-688978425

set -e
set -o pipefail

if [[ -n "${ECS_FARGATE}" ]]; then
  echo "datadog agent starting up in ecs!"
  echo "trying to get task_arn from metadata endpoint..."

  until [ -n "${task_arn}" ]; do
    task_arn=$(curl --silent 169.254.170.2/v2/metadata | jq --raw-output '.TaskARN | split("/") | last')
  done

  echo "got it. starting up with task_arn $task_arn"
  export DD_HOSTNAME=task-$task_arn

fi

/init