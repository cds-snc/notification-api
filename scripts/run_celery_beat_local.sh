#!/bin/sh

# runs the celery beat process. This runs the periodic tasks

set -e

celery -A run_celery.notify_celery beat --loglevel=INFO
