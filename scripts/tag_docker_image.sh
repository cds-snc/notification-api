#!/bin/bash
set -e

MANIFEST=$(aws ecr batch-get-image --repository-name notification_api --image-ids imageTag="$1" --region "$3" --query 'images[].imageManifest' --output text)
aws ecr put-image --repository-name notification_api --image-tag "$2" --image-manifest "$MANIFEST" --region "$3"