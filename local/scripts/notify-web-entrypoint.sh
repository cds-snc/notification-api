#!/bin/bash
set -x

###################################################################
# This script will get executed *once* the Docker container has 
# been built. Commands that need to be executed with all available
# tools and the filesystem mount enabled should be located here. 
###################################################################

cd /app 

# We need to override the default database URI to provide the database
# container hostname in the URI string.
#cp .env.example .env

make generate-version-file
pip3 install -r requirements.txt

# Upgrade schema of the notification_api database.
flask db upgrade

# Bubble up the main Docker command to container.
exec "$@"
