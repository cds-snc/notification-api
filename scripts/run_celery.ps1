$ENV:FORKED_BY_MULTIPROCESSING=1

celery --app run_celery worker --pidfile="$env:TEMP\celery.pid" --pool=solo --loglevel=DEBUG --concurrency=1 -Q "database-tasks,-priority-database-tasks.fifo,-normal-database-tasks,-bulk-database-tasks,job-tasks,notify-internal-tasks,periodic-tasks,priority-tasks,normal-tasks,bulk-tasks,reporting-tasks,research-mode-tasks,retry-tasks,send-sms-high,send-sms-medium,send-sms-low,service-callbacks,service-callbacks-retry,delivery-receipts"
