set -ex

###################################################################
# This script will get executed *once* the Docker container has 
# been built. Commands that need to be executed with all available
# tools and the filesystem mount enabled should be located here. 
#
# The PostgreSQL Docker image has an extension mechanism that does 
# not necessitate to override the entrypoint or main command. One
# simply has to copy a shell script into the 
# /docker-entrypoint-initdb.d/ initialization folder. 
###################################################################

# Notify database setup.
createdb --user=postgres notification_api
