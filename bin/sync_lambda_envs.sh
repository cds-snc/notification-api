#!/bin/sh

# This script will retrieve notification environment variables from AWS parameter store
# Since lambda & k8s environments have some variance, this script will remove any environment
# variable that is already set when run within the lambda runtime environment

TMP_ENV_FILE="/tmp/.env"

var_expand() {
  if [ -z "${1-}" ] || [ $# -ne 1 ]; then
    printf 'var_expand: expected one argument\n' >&2;
    return 1;
  fi
  eval printf '%s' "\"\${$1?}\"" 2> /dev/null # Variable double substitution to be able to check for variable
}

load_non_existing_envs() {
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

    if [ -z $(var_expand $key) ]; then # Check if environment variable doesn't exist
      export "${key}=${value}"
    fi
    
  done < $TMP_ENV_FILE
}

if [ ! -f "$TMP_ENV_FILE" ]; then # Only setup envs once per lambda lifecycle
  echo "Retrieving environment parameters"
  aws ssm get-parameters --region ca-central-1 --with-decryption --names ENVIRONMENT_VARIABLES --query 'Parameters[*].Value' --output text > "$TMP_ENV_FILE"
fi

load_non_existing_envs
