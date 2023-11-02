#!/bin/sh

# runs the celery beat process. This runs the periodic tasks

set -e

# Check and see if this is running in K8s and if so, wait for cloudwatch agent
if [[ ! -z "${STATSD_HOST}" ]]; then

    echo "Initializing... Waiting for CWAgent to become ready."
    while :
    do
        if  nc -vz $STATSD_HOST 25888; then
            echo "CWAgent is Ready."
            break;
        else
            echo "Waiting for CWAgent to become ready."
            sleep 1
        fi
    done
fi

celery -A run_celery.notify_celery beat --loglevel=INFO
