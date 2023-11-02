#!/bin/sh

# runs celery with only the send-email-* queues

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

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

# TODO: we shouldn't be using the send-email-tasks queue anymore - once we verify this we can remove it
celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency=${CELERY_CONCURRENCY-4} -Q send-email-tasks,send-email-high,send-email-medium,send-email-low
