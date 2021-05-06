#!/bin/sh

set -e

celery -A run_celery.notify_celery worker --loglevel=INFO --concurrency=10 -Q bulk-tasks,send-email-tasks
