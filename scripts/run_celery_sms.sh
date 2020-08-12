#!/bin/sh

set -e

celery -A run_celery.notify_celery worker --loglevel=INFO --concurrency=1 -Q send-sms-tasks
