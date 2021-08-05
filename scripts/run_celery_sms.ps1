$ENV:FORKED_BY_MULTIPROCESSING=1

celery --app run_celery.notify_celery worker --pidfile="$env:TEMP\celery_sms.pid" --pool=solo --loglevel=INFO --concurrency=1 -Q send-throttled-sms-tasks