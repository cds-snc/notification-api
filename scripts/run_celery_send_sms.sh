#!/bin/sh

# runs celery with only the send-sms-* queues

set -e

echo "Start celery, concurrency: 6"

# TODO: we shouldn't be using the send-sms-tasks queue anymore - once we verify this we can remove it
celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency=6 -Q send-sms-tasks,send-sms-high,send-sms-medium,send-sms-low
