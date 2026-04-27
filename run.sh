#!/bin/bash

#This script is used when running the app through docker. It handles scheduling the script.

#Default interval is 300 seconds (5 minutes) if not set

INTERVAL=${SCRIPT_INTERVAL:-300}

# Start the web UI in the background (default enabled)
if [ "${WEBUI_ENABLED:-true}" = "true" ]; then

    # If WEBUI_PORT is set, change the default listening port
    _WEBUI_ARGS=()
    if [ -n "${WEBUI_PORT:-}" ]; then
        _NUMBERRE='^[0-9]+$'

        if [[ "${WEBUI_PORT}" =~ $_NUMBERRE ]]; then
            _WEBUI_ARGS+=("--port" "${WEBUI_PORT}")
        else
            echo "WEBUI_PORT is not numeric, ignoring." 1>&2
        fi
    fi

    python -u /app/webui/webui.py "${_WEBUI_ARGS[@]}" "$@" &
fi

while true; do
    if ps aux | grep "[s]oularr.py" > /dev/null; then
        echo "Soularr is already running. Exiting..."
    else
        #Pass in the arguments given to the bash script over to the Python script
        python -u /app/soularr.py "$@"
    fi

    dt=$(date '+%d/%m/%Y %H:%M:%S');
    echo "$dt - Waiting for $INTERVAL seconds before checking again..."
    sleep $INTERVAL
done
