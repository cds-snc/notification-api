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

# Smoke test
# requires files .env_staging and .env_prod to the root of the project
echo -e "alias smoke-staging='cd /workspace && cp .env_smoke_staging tests_smoke/.env && make smoke-test'" >> ~/.zshrc
echo -e "alias smoke-prod='cd /workspace && cp .env_smoke_prod tests_smoke/.env && make smoke-test'" >> ~/.zshrc

cd /workspace 

# Warm up git index prior to display status in prompt else it will 
# be quite slow on every invocation of starship.
git status

make generate-version-file
pip3 install -r requirements.txt
pip3 install -r requirements_for_test.txt

# Install virtualenv to support running the isolated make freeze-requirements from within the devcontainer
pip3 install virtualenv

# Upgrade schema of the notification_api database.
flask db upgrade
