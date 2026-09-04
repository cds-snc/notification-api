#!/bin/sh

# runs the celery beat process. This runs the scheduler.

set -e

celery -A run_celery.notify_celery beat --loglevel=INFO
