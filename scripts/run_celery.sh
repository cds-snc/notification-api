#!/bin/sh

set -e

celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --concurrency=4 -Q database-tasks,job-tasks,notify-internal-tasks,periodic-tasks,priority-tasks,reporting-tasks,research-mode-tasks,retry-tasks,send-email-tasks,service-callbacks
