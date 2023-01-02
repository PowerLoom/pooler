#!/bin/bash

# Waiting for other processes to start
sleep 15

python -m pooler.processhub_cmd start EpochCallbackManager  
sleep 3 

python -m pooler.processhub_cmd start SystemEpochDetector  
sleep 3

exit 0
