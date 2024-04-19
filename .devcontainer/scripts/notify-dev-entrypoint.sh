#!/bin/bash
set -ex

###################################################################
# This script will get executed *once* the Docker container has
# been built. Commands that need to be executed with all available
# tools and the filesystem mount enabled should be located here.
###################################################################

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
echo -e "alias poe='poetry run poe'" >> ~/.zshrc

# Smoke test
# requires adding files .env_staging and .env_prod to the root of the project
echo -e "alias smoke-staging='cd /workspace && cp .env_smoke_staging tests_smoke/.env && poetry run make smoke-test'" >> ~/.zshrc
echo -e "alias smoke-prod='cd /workspace && cp .env_smoke_prod tests_smoke/.env && poetry run make smoke-test'" >> ~/.zshrc

cd /workspace

# Poetry autocomplete
echo -e "fpath+=/.zfunc" >> ~/.zshrc
echo -e "autoload -Uz compinit && compinit"

pip install poetry==${POETRY_VERSION}
export PATH=$PATH:/home/vscode/.local/bin/
which poetry
poetry --version

# Initialize poetry autocompletions
mkdir ~/.zfunc
touch ~/.zfunc/_poetry
poetry completions zsh > ~/.zfunc/_poetry

make generate-version-file

# Install dependencies
poetry install

# Poe the Poet plugin tab completions
touch ~/.zfunc/_poe
poetry run poe _zsh_completion > ~/.zfunc/_poe

# Upgrade schema of the notification_api database.
poetry run flask db upgrade

# install npm deps (i.e. cypress)
cd tests_cypress && npm install && npx cypress install && cd ..