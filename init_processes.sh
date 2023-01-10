#!/bin/bash

# Waiting for other processes to start
echo 'waiting for other services..';
sleep 10

echo 'initializing queues..';
poetry run python -m pooler.init_rabbitmq

pm2 start pm2.config.js

# Waiting for other processes to start
echo 'waiting for processes to start..';
sleep 10

poetry run python -m pooler.processhub_cmd start EpochCallbackManager
sleep 3

poetry run python -m pooler.processhub_cmd start SystemEpochDetector

echo 'started all pooler scripts';

pm2 logs --lines 1000