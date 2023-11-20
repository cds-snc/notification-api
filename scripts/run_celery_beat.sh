#!/bin/sh

set -e

# Runs the celery beat process, i.e the Celery periodic tasks.

celery -A run_celery.notify_celery beat --loglevel=INFO
