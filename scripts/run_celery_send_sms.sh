#!/bin/sh

# runs celery with only the send-sms-* queues

init()
{
     # Wait for cwagent to become available.   
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
}

set -e

if [[ -z "${STATSD_HOST}" ]]; then
    init
fi

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

# TODO: we shouldn't be using the send-sms-tasks queue anymore - once we verify this we can remove it
celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency=${CELERY_CONCURRENCY-4} -Q send-sms-tasks,send-sms-high,send-sms-medium,send-sms-low
