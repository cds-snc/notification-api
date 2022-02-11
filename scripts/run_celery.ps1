$ENV:FORKED_BY_MULTIPROCESSING=1

celery --app run_celery worker --pidfile="$env:TEMP\celery.pid" --pool=solo --loglevel=DEBUG --concurrency=1 -Q "database-tasks,job-tasks,notify-internal-tasks,periodic-tasks,priority-tasks,bulk-tasks,reporting-tasks,research-mode-tasks,retry-tasks,send-sms-tasks,send-email-tasks,service-callbacks,delivery-receipts"
