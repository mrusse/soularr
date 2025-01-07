#!/bin/bash

#This script is used when running the app through docker. It handles scheduling the script.

# Default interval is 300 seconds (5 minutes) if not set
INTERVAL=${SCRIPT_INTERVAL:-300}

while true; do
    if ps aux | grep "[s]oularr.py" > /dev/null; then
        echo "Soularr is already running. Exiting..."
    else
        # Pass in the arguments given to the bash script over to the Python script
        python -u /app/soularr.py "$@"
    fi

    dt=$(date '+%d/%m/%Y %H:%M:%S');
    echo "$dt - Waiting for $INTERVAL seconds before checking again..."
    sleep $INTERVAL
done