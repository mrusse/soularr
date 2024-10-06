#!/bin/bash
cd /path/to/soularr/python/script

dt=$(date '+%d/%m/%Y %H:%M:%S');
echo "Starting Soularr! $dt"

if ps aux | grep "[s]oularr.py" > /dev/null; then
    echo "Soularr is already running. Exiting..."
else
    python soularr.py
fi

# This script is just an example. Will need to be modified to fit your needs.
# I have a cronjob that runs a script very similar to this every 5 minutes on my unraid server.