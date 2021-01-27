#!/usr/bin/env bash
set -ex

###############################################################################
# This script will get executed *once* the Docker container has been built. 
# Commands that need to be executed with all available tools and the filesystem 
# mount enabled should be located here. 
#
# The PostgreSQL Docker image has an extension mechanism that does not 
# necessitate to override the entrypoint or main command. One simply has to 
# copy a shell script into the /docker-entrypoint-initdb.d/ initialization 
# folder. 
###############################################################################

# Create reader user meant for testing writer/reader replica functionality.
# Getting through the `psql` client is a mean to set the password as one cannot
# set the password via the `createuser` command-line utility.
psql -f create-role-reader.sql postgresql://postgres:postgres@localhost:5432
