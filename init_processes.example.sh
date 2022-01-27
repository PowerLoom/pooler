#!/bin/zsh

python launch_process_hub_core.py > /dev/null 2>&1 &
echo "Launched Process Hub Core..."
sleep 3
python processhub_cmd.py start EpochCallbackManager
sleep 3
python processhub_cmd.py start SystemEpochFinalizer
sleep 3
python processhub_cmd.py start SystemEpochCollator
sleep 3
python processhub_cmd.py start SystemLinearEpochClock