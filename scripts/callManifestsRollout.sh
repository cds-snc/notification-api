#!/bin/bash
GITHUB_SHA=$1
PAYLOAD="{\"ref\":\"main\",\"inputs\":{\"docker_sha\":\"$GITHUB_SHA\"}}"


RESPONSE=$(curl -w '%{http_code}\n' \
  -o /dev/null -s \
  -L -X POST -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $WORKFLOW_PAT" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/cds-snc/notification-manifests/actions/workflows/api-rollout-k8s-staging.yaml/dispatches \
  -d "$PAYLOAD")

if [ "$RESPONSE" != 204 ]; then
  echo "ERROR CALLING MANIFESTS ROLLOUT: HTTP RESPONSE: $RESPONSE"
  exit 1
fi
