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

cd /workspace 

# Warm up git index prior to display status in prompt else it will 
# be quite slow on every invocation of starship.
git status

# We need to override the default database URI to provide the database
# container hostname in the URI string.
cp .env.example .env
echo -e "\nSQLALCHEMY_DATABASE_URI=postgresql://postgres@db/notification_api" >> .env

make generate-version-file
pip3 install -r requirements.txt
pip3 install -r requirements_for_test.txt

# Upgrade schema of the notification_api database.
flask db upgrade

wall "The dev container entrypoint setup is complete!"

# Bubble up the main Docker command to container.
exec "$@"