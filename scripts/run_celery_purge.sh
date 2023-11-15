#!/bin/sh

set -e

printf "\n--------------------------------------------------\n"
printf "                   WARNING!!!!\n"
printf "    This script is for local development only!\n"
printf "  It will delete everything in the celery queues.\n"
printf "--------------------------------------------------\n"
printf "Are you sure you want to continue?"
read -p "If so, type 'purge'> " check
    case $check in
        purge ) echo "purging!"; celery -A run_celery.notify_celery purge -f; break;;
        * ) printf "\nNot purging\n";;
    esac

