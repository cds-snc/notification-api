#!/bin/sh

# runs celery with only the throttled sms sending queue

set -e

celery -A run_celery.notify_celery worker --loglevel=INFO --concurrency=1 -Q send-throttled-sms-tasks
