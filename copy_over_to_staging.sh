#!/bin/zsh

files_list=("callback_modules/helpers.py" "callback_modules/liquidity.py" "callback_modules/trade_volume.py" "epoch_broadcast_callback_manager.py" "eth_log_dist_worker.py" "launch_process_hub_core.py" "log_fetch_service.py" "process_hub_core.py" "rpc_helper.py" "system_epoch_collator.py" "system_epoch_finalizer.py" "system_ticker_linear.py")

for fname in "${files_list[@]}"
do
  echo "Copying over $fname"
  scp $fname ubuntu@3.16.206.36:/home/ubuntu/polymarket-adapter/$fname
done