#!/bin/bash
set -ex 

###################################################################
# This script will get executed *once* the Docker container has 
# been built. Commands that need to be executed with all available
# tools and the filesystem mount enabled should be located here. 
###################################################################

# Define aliases
echo -e "\n\n# User's Aliases" >> ~/.bashrc
echo -e "alias fd=fdfind" >> ~/.bashrc
echo -e "alias l='ls -al --color'" >> ~/.bashrc
echo -e "alias ls='exa'" >> ~/.bashrc
echo -e "alias l='exa -alh'" >> ~/.bashrc
echo -e "alias ll='exa -alh@ --git'" >> ~/.bashrc
echo -e "alias lt='exa -al -T -L 2'" >> ~/.bashrc

cd /workspace 

# Warm up git index prior to display status in prompt else it will 
# be quite slow on every invocation of starship.
git status

make generate-version-file
pip3 install -r requirements.txt
pip3 install -r requirements_for_test.txt

# Upgrade schema of the notification_api database.
flask db upgrade
