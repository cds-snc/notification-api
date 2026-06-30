#!/bin/sh

set -e

# Runs celery with all celery queues except send-throttled-sms-tasks,
# send-sms-*, send-email-*, periodic-tasks, and job-tasks.

echo "Start celery, concurrency: ${CELERY_CONCURRENCY-4}"

# Include the periodic and jobs tasks in the same worker if FF_IMPROVE_CELERY_WORKER_ISOLATION 
# is not enabled, otherwise run them in a separate worker. 
if [ "${FF_IMPROVE_CELERY_WORKER_ISOLATION:-false}" = "true" ]; then
	celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --pool="${CELERY_POOL:-gevent}" --concurrency="${CELERY_CONCURRENCY-4}" -Q -priority-database-tasks.fifo,-normal-database-tasks,-bulk-database-tasks,notify-internal-tasks,priority-tasks,normal-tasks,bulk-tasks,reporting-tasks,research-mode-tasks,retry-tasks,service-callbacks,service-callbacks-retry,delivery-receipts
else
	celery -A run_celery.notify_celery worker --pidfile="/tmp/celery.pid" --loglevel=INFO --pool="${CELERY_POOL:-gevent}" --concurrency="${CELERY_CONCURRENCY-4}" -Q -priority-database-tasks.fifo,-normal-database-tasks,-bulk-database-tasks,job-tasks,notify-internal-tasks,periodic-tasks,priority-tasks,normal-tasks,bulk-tasks,reporting-tasks,research-mode-tasks,retry-tasks,service-callbacks,service-callbacks-retry,delivery-receipts
fi
