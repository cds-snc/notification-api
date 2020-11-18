#!/bin/bash
set -ex 

###################################################################
# This script will get executed *once* the Docker container has 
# been built. Commands that need to be executed with all available
# tools and the filesystem mount enabled should be located here. 
###################################################################

# We want to enable broadcast message which by default is disabled.
sed '/mesg/d' ~/.profile > ~/.profile.bak && mv ~/.profile.bak ~/.profile
echo -e "\ntest -t 0 && mesg n" >> ~/.profile

# Define aliases
echo -e "\n\n# User's Aliases" >> ~/.profile
echo -e "alias fd=fdfind" >> ~/.profile
echo -e "alias l='ls -al --color'" >> ~/.profile
echo -e "alias ls='exa'" >> ~/.profile
echo -e "alias l='exa -alh'" >> ~/.profile
echo -e "alias ll='exa -alh@ --git'" >> ~/.profile
echo -e "alias lt='exa -al -T -L 2'" >> ~/.profile

cd /workspace 

# Warm up git index prior to display status in prompt else it will 
# be quite slow on every invocation of starship.
git status

make generate-version-file
pip3 install -r requirements.txt
pip3 install -r requirements_for_test.txt

# Upgrade schema of the notification_api database.
flask db upgrade

wall "The dev container entrypoint setup is complete!"

# Bubble up the main Docker command to container.
exec "$@"