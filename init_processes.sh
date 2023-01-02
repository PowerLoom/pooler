#!/bin/bash

# Waiting for other processes to start
sleep 10

poetry run python -m pooler.processhub_cmd start EpochCallbackManager  
sleep 3 

poetry run python -m pooler.processhub_cmd start SystemEpochDetector  