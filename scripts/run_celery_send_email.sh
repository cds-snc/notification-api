#!/bin/sh

set -e

# Runs celery with only the send-email-* queues.

# Check and see if this is running in K8s and if so, wait for cloudwatch agent
if [ -n "${STATSD_HOST}" ]; then
    echo "Initializing... Waiting for CWAgent to become ready within the next 30 seconds."
    timeout=30
    while [ $timeout -gt 0 ]; do
        if nc -vz "$STATSD_HOST" 25888; then
            echo "CWAgent is Ready."
            break
        else
            echo "Waiting for CWAgent to become ready."
            sleep 1
            timeout=$((timeout - 1))
        fi
    done
    
    if [ $timeout -eq 0 ]; then
        echo "Timeout reached. CWAgent did not become ready in 30 seconds."
        exit 1
    fi
fi

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

# TODO: we shouldn't be using the send-email-tasks queue anymore, once we verify this we can remove it
celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency="${CELERY_CONCURRENCY-4}" -Q send-email-tasks,send-email-high,send-email-medium,send-email-low
