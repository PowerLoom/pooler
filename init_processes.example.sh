#!/bin/zsh

pm2 start launch_process_hub_core.py --name=uniswap-pooler-processhub-core
echo "Launched Uniswap Pooler Process Hub Core..."
echo "Launched Process Hub Core..."
sleep 3
python processhub_cmd.py start EpochCallbackManager
sleep 3
python processhub_cmd.py start SystemEpochFinalizer
sleep 3
python processhub_cmd.py start SystemEpochCollator
sleep 3
python processhub_cmd.py start SystemLinearEpochClock