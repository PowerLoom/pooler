#!/bin/bash

echo 'starting processes...';
pm2 start pm2.config.js

# Waiting for other processes to start
echo 'waiting for processes to start..';
sleep 10

poetry run python -m pooler.processhub_cmd start ProcessorDistributor
sleep 3

poetry run python -m pooler.processhub_cmd start SystemEventDetector

echo 'started all pooler scripts';

pm2 logs --lines 1000
