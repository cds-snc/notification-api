#!/bin/sh

set -e

function get_celery_pids {
  # get the PIDs of the process whose parent is the main celery process, saved in celery.pid
  # print only pid and their command, get the ones with "celery" in their name
  # and keep only these PIDs

  set +o pipefail # so grep returning no matches does not premature fail pipe
  APP_PIDS=$(pstree -p `cat /tmp/celery.pid` | sed 's/\(.*\)-celery(\(\d*\))/\2/')
  set -o pipefail # pipefail should be set everywhere else
}

function ensure_celery_is_running {
  if [ "${APP_PIDS}" = "" ]; then
    echo "There are no celery processes running, this container is bad"
    exit 1
  fi

  for APP_PID in ${APP_PIDS}; do
      kill -0 ${APP_PID} 2&>/dev/null || return 1
  done
}

get_celery_pids

ensure_celery_is_running