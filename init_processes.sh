#!/bin/bash

echo 'starting processes...';
pm2 start pm2.config.js

echo 'registering projects...';
poetry run python -m pooler.register_projects || exit 1


# Waiting for other processes to start
echo 'waiting for processes to start..';
sleep 10

poetry run python -m pooler.processhub_cmd start EpochCallbackManager
sleep 3

poetry run python -m pooler.processhub_cmd start SystemEpochDetector

echo 'started all pooler scripts';

pm2 logs --lines 1000
