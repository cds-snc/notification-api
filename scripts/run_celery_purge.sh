#!/bin/sh

set -e

printf "\n--------------------------------------------------\n"
printf "                   WARNING!!!!\n"
printf "    This script is for local development only!\n"
printf "  It will delete everything in the celery queues.\n"
printf "\n--------------------------------------------------\n"
printf "Are you sure you want to continue?"
echo "If so, type 'purge'> \c"
read -r check
    case $check in
        purge ) echo "purging!"; celery -A run_celery.notify_celery purge -f;;
        * ) printf "\nNot purging\n";;
    esac

