#!/bin/bash

# poetry run python -m snapshotter.snapshotter_id_ping
# ret_status=$?

# if [ $ret_status -ne 0 ]; then
#     echo "Snapshotter identity check failed on protocol smart contract"
#     exit 1
# fi
# echo 'starting processes...';
pm2 start pm2.config.js

# Waiting for other processes to start
echo 'waiting for processes to start..';
sleep 10

# poetry run python -m snapshotter.processhub_cmd start ProcessorDistributor
# sleep 3

# poetry run python -m snapshotter.processhub_cmd start SystemEventDetector

# echo 'started all snapshotter scripts';

pm2 logs --lines 1000
