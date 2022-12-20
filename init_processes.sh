#!/bin/bash

# Waiting for other processes to start
sleep 15

python processhub_cmd.py start EpochCallbackManager  
sleep 3 
