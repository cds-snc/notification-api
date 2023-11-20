#!/bin/bash
# Check and see if this is running in K8s and if so, wait for cloudwatch agent
if [ -n "${STATSD_HOST}" ]; then
    echo "Initializing... Waiting for CWAgent to become ready within the next 30 seconds."
    timeout=30
    while [ $timeout -gt 0 ]; do
        if nc -vz "$STATSD_HOST" 25888; then
            echo "CWAgent is Ready."
            break
        else
            echo "Waiting for CWAgent to become ready."
            sleep 1
            timeout=$((timeout - 1))
        fi
    done
    
    if [ $timeout -eq 0 ]; then
        echo "Timeout reached. CWAgent did not become ready in 30 seconds."
        exit 1
    fi
fi
