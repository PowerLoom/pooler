#!/bin/zsh

files_list=("callback_modules/helpers.py" "callback_modules/pair_total_reserves.py" "message_models.py" "redis_conn.py" \
"redis_keys.py" "system_ticker_linear.py" "uniswap_functions.py")

for fname in "${files_list[@]}"
do
  echo "Copying over $fname"
  scp $fname ubuntu@powerloom-staging:/home/ubuntu/fpmm-pooler-internal/$fname
done