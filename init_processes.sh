#!/bin/bash

echo 'starting processes...';
pm2 start pm2.config.js

# Waiting for other processes to start
echo 'waiting for processes to start..';
sleep 10

poetry run python -m snapshotter.processhub_cmd start ProcessorDistributor
sleep 3

poetry run python -m snapshotter.processhub_cmd start SystemEventDetector

echo 'started all snapshotter scripts';

pm2 logs --lines 1000
