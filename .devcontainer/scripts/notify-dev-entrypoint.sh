#!/bin/bash
set -ex

###################################################################
# This script will get executed *once* the Docker container has
# been built. Commands that need to be executed with all available
# tools and the filesystem mount enabled should be located here.
###################################################################

git config --global --add safe.directory /workspace

# Define aliases
echo -e "\n\n# User's Aliases" >> ~/.zshrc
echo -e "alias fd=fdfind" >> ~/.zshrc
echo -e "alias l='ls -al --color'" >> ~/.zshrc
echo -e "alias ls='exa'" >> ~/.zshrc
echo -e "alias l='exa -alh'" >> ~/.zshrc
echo -e "alias ll='exa -alh@ --git'" >> ~/.zshrc
echo -e "alias lt='exa -al -T -L 2'" >> ~/.zshrc

# Kubectl aliases and command autocomplete
echo -e "alias k='kubectl'" >> ~/.zshrc
echo -e "alias k-staging='aws eks --region ca-central-1 update-kubeconfig --name notification-canada-ca-staging-eks-cluster'" >> ~/.zshrc
echo -e "alias k-prod='aws eks --region ca-central-1 update-kubeconfig --name notification-canada-ca-production-eks-cluster'" >> ~/.zshrc
echo -e "source <(kubectl completion zsh)" >> ~/.zshrc
echo -e "complete -F __start_kubectl k" >> ~/.zshrc

# Smoke test
# requires adding files .env_staging and .env_prod to the root of the project
echo -e "alias smoke-local='cd /workspace && cp .env_smoke_local tests_smoke/.env && poetry run make smoke-test-local'" >> ~/.zshrc
echo -e "alias smoke-staging='cd /workspace && cp .env_smoke_staging tests_smoke/.env && poetry run make smoke-test'" >> ~/.zshrc
echo -e "alias smoke-prod='cd /workspace && cp .env_smoke_prod tests_smoke/.env && poetry run make smoke-test'" >> ~/.zshrc
echo -e "alias smoke-dev='cd /workspace && cp .env_smoke_dev tests_smoke/.env && poetry run make smoke-test-dev'" >> ~/.zshrc

echo -e "# fzf key bindings and completion" >> ~/.zshrc
echo -e "source /usr/share/doc/fzf/examples/key-bindings.zsh" >> ~/.zshrc
echo -e "source /usr/share/doc/fzf/examples/completion.zsh" >> ~/.zshrc


cd /workspace

ENV_FILE=".env"
ENV_EXAMPLE_FILE=".env.example"

# Check if .env exists
if [ ! -f "$ENV_FILE" ]; then
  echo "$ENV_FILE does not exist."

  # Check if .env.example exists
  if [ -f "$ENV_EXAMPLE_FILE" ]; then
    echo -e "Creating $ENV_FILE from $ENV_EXAMPLE_FILE."
    {
      echo "# TODO: Populate this .env file with contents from \"[CDS Platform - Notify Local] api .env\" in 1Password"
      cat "$ENV_EXAMPLE_FILE"
    } > "$ENV_FILE"
  else
    echo "Warning: $ENV_EXAMPLE_FILE does not exist. Creating empty $ENV_FILE."
    echo "# TODO: Populate this .env file with contents from \"[CDS Platform - Notify Local] api .env\" in 1Password" > "$ENV_FILE"
  fi
fi

# Poetry autocomplete
echo -e "fpath+=/.zfunc" >> ~/.zshrc
echo -e "autoload -Uz compinit && compinit" >> ~/.zshrc

pip install poetry=="${POETRY_VERSION}" poetry-plugin-sort
export PATH=$PATH:/home/vscode/.local/bin/
which poetry
poetry --version

# Disable poetry auto-venv creation
poetry config virtualenvs.create false

# Initialize poetry autocompletions
mkdir -p ~/.zfunc
touch ~/.zfunc/_poetry
poetry completions zsh > ~/.zfunc/_poetry

# Manually create and activate a virtual environment with a static path
python -m venv "${POETRY_VENV_PATH}"
source "${POETRY_VENV_PATH}/bin/activate"

# Ensure newly created shells activate the poetry venv
echo "source ${POETRY_VENV_PATH}/bin/activate" >> ~/.zshrc

make generate-version-file

# Install dependencies for this repo (no installable package artifact in this project)
poetry install --no-root

# Install pre-commit hooks
poetry run pre-commit install

# Upgrade schema of the notification_api database.
# During first container startup, postgres can be briefly unavailable.
db_upgrade_attempts=5
db_upgrade_delay_seconds=5
for attempt in $(seq 1 "$db_upgrade_attempts"); do
  if poetry run flask db upgrade; then
    break
  fi

  if [ "$attempt" -lt "$db_upgrade_attempts" ]; then
    echo "flask db upgrade failed (attempt ${attempt}/${db_upgrade_attempts}). Retrying in ${db_upgrade_delay_seconds}s..."
    sleep "$db_upgrade_delay_seconds"
  else
    echo "WARNING: flask db upgrade failed after ${db_upgrade_attempts} attempts. Run 'poetry run flask db upgrade' once the database is ready."
  fi
done

# Set up git blame to ignore certain revisions e.g. sweeping code formatting changes.
git config blame.ignoreRevsFile .git-blame-ignore-revs

# install npm deps (i.e. cypress)
cd tests_cypress && npm install && npx cypress install && cd ..
