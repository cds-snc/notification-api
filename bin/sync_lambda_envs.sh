#!/bin/sh

# This script will retrieve notification environment variables from AWS parameter store

TMP_ENV_FILE="/tmp/.env"

load_all_envs() {
  local envFile=${1:-.env}
  local isComment='^[[:space:]]*#'
  local isBlank='^[[:space:]]*$'
  while IFS= read -r line; do
    if echo $line | grep -Eq $isComment; then # Ignore comment line
      continue
    fi
    if echo $line | grep -Eq $isBlank; then # Ignore blank line
      continue
    fi
    key=$(echo "$line" | cut -d '=' -f 1)
    value=$(echo "$line" | cut -d '=' -f 2-)

    # Always export (override any existing static value)
    export "${key}=${value}"
    
  done < $TMP_ENV_FILE
}

if [ ! -f "$TMP_ENV_FILE" ]; then # Only setup envs once per lambda lifecycle
  echo "Retrieving environment parameters"
  aws ssm get-parameters --region ca-central-1 --with-decryption --names ENVIRONMENT_VARIABLES --query 'Parameters[*].Value' --output text > "$TMP_ENV_FILE"
fi

load_all_envs
