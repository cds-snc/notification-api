#!/bin/sh

set -e

celery -A run_celery.notify_celery sms --loglevel=INFO --concurrency=1 -queue send-sms-tasks
