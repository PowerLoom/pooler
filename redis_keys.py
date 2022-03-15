from dynaconf import settings
# TODO: clean up polymarket specific keys as we develop the callback workers
uniswap_failed_pair_total_reserves_epochs_redis_q_f = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:failedPairTotalReservesEpochs'
uniswap_pair_total_reserves_processing_status = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:PairTotalReservesProcessingStatus'
uniswap_pair_contract_tokens_addresses = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:PairContractTokensAddresses'
uniswap_pair_contract_tokens_data = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:PairContractTokensData'
uniswap_pair_total_reserves_last_snapshot = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:LastCachedPairReserve'
uniswap_pair_cached_token_price = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:cachedPairPrice'
uniswap_pair_contract_V2_pair_data = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:contractV2PairCachedData'
uniswap_cb_broadcast_processing_logs_zset = 'uniswap:broadcastID:' + settings.NAMESPACE + ':{}:processLogs'

powerloom_broadcast_id_zset = 'powerloom:broadcastID:' + settings.NAMESPACE + ':broadcastProcessingStatus'
eth_log_request_data_f = 'powerloom:ethLogs:'+settings.NAMESPACE+':requestId:{}:results'  # request UUID
