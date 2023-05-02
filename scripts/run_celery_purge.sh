#!/bin/sh

set -e

echo "\n--------------------------------------------------\n"
echo "                   WARNING!!!!\n"
echo "    This script is for local development only!\n"
echo "  It will delete everything in the celery queues.\n"
echo "--------------------------------------------------\n"
echo "Are you sure you want to continue?"
read -p "If so, type 'purge'> " check
    case $check in
        purge ) echo "purging!"; celery -A run_celery.notify_celery purge -f; break;;
        [Nn]* ) exit;;
        * ) echo "\nNot purging\n";;
    esac

