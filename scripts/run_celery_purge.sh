#!/bin/sh

set -e

celery -A run_celery.notify_celery purge -f
