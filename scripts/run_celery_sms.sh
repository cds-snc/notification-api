#!/bin/sh

# runs celery with only the throttled sms sending queue

set -e

if [[ -z "${STATSD_HOST}" ]]; then
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

celery -A run_celery.notify_celery worker --loglevel=INFO --concurrency=1 -Q send-throttled-sms-tasks
