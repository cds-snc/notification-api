#!/usr/bin/env bash
set -ex

###############################################################################
# This script will get executed *once* the Docker container has been built.
# Commands that need to be executed with all available tools and the filesystem
# mount enabled should be located here.
###############################################################################

# Create reader user meant for testing writer/reader replica functionality.
createuser reader -w -D -R -h 127.0.0.1 -p 5432 -U postgres

# Bubble up the main Docker command to container.
exec "$@"
