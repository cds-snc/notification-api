#!/bin/sh

# runs celery with only the throttled sms sending queue

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

# Check and see if this is running in K8s and if so, wait for cloudwatch agent
if [[ -z "${STATSD_HOST}" ]]; then
    init
fi

celery -A run_celery.notify_celery worker --loglevel=INFO --concurrency=1 -Q send-throttled-sms-tasks
