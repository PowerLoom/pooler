#!/bin/bash

# Waiting for other processes to start
sleep 15

python processhub_cmd.py start EpochCallbackManager  
sleep 3 
python processhub_cmd.py start SystemEpochFinalizer  
sleep 3 
python processhub_cmd.py start SystemEpochCollator 
sleep 3 
python processhub_cmd.py start SystemLinearEpochClock --begin $1
