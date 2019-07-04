#!/bin/bash

set -e

celery -A run_celery.notify_celery beat --loglevel=INFO
