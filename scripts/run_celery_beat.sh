#!/bin/sh

set -e

if [ "$1" = "purge" ]; then
    celery -A run_celery.notify_celery purge -f || true
fi

celery -A run_celery.notify_celery beat --loglevel=INFO
