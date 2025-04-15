#!/bin/sh

set -e

PRIO_PID_LOG=/tmp/celery_priority.pid
ALL_PID_LOG=/tmp/celery_all.pid

# Triggers when a SIGTERM is caught (trap command below)
sigterm_handler() {
  echo "Start gracefull worker shutdown..."
  # Gracefully shutdown workers
  kill -TERM "$WORKER_PRIO_PID"
  kill -TERM "$WORKER_ALL_PID"

  # Wait for them to shut down, then cleanup the PID files
  wait "$WORKER_PRIO_PID" && rm -f $PRIO_PID_LOG
  wait "$WORKER_ALL_PID" && rm -f $ALL_PID_LOG
  echo "...Workers shut down gracefully"
  # 128 + 15 -- SIGTERM
  exit 143
}

# Execute the sigterm_handler function if this PID receives a SIGTERM
trap sigterm_handler SIGTERM

echo "Start the Priority queue worker"
# rm in case of manual shutdown (local)
rm -f $PRIO_PID_LOG
# Run the worker async and capture the PID it was assigned
ddtrace-run celery -A run_celery.notify_celery worker -n priority --pidfile="$PRIO_PID_LOG" --loglevel=INFO --concurrency=$CELERY_CONCURRENCY -Q send-sms-tasks,send-email-tasks,lookup-contact-info-tasks,lookup-va-profile-id-tasks &
WORKER_PRIO_PID=$!
echo "Worker: Priority PID: $WORKER_PRIO_PID"

echo "Start the All queue worker"
# rm in case of manual shutdown (local)
rm -f $ALL_PID_LOG
# Run the worker async and capture the PID it was assigned
ddtrace-run celery -A run_celery.notify_celery worker -n all --pidfile="$ALL_PID_LOG" --loglevel=INFO --concurrency=$CELERY_CONCURRENCY &
WORKER_ALL_PID=$!
echo "Worker: All PID: $WORKER_ALL_PID"

# The script waits as long as these two are running. 
# Normal use case would terminate this script in the sigterm_handler, not after these two
wait "$WORKER_PRIO_PID"
wait "$WORKER_ALL_PID"
