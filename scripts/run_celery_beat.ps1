$ENV:FORKED_BY_MULTIPROCESSING=1

celery -A run_celery beat --pidfile="$env:TEMP\celery-beat.pid" --loglevel=INFO