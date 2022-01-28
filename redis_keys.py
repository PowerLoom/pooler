from dynaconf import settings
# TODO: clean up polymarket specific keys as we develop the callback workers
uniswap_failed_pair_total_reserves_epochs_redis_q_f = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:failedPairTotalReservesEpochs'
uniswap_pair_total_reserves_processing_status = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:PairTotalReservesProcessingStatus'

polymarket_base_trade_vol_key_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:TradeVolumeBase'
polymarket_consolidated_trade_vol_key_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:consolidatedTradeVolume'
polymarket_queued_trade_vol_epochs_zset_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:queuedTradeVolumeEpochs'
polymarket_trade_vol_epoch_details_hset_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:tradeVolumeEpochs'
polymarket_seed_trade_lock = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:tradeVolume:Lock'
powerloom_broadcast_id_processing_set = 'polymarket:broadcastID:' + settings.NAMESPACE + ':{}:broadcastProcessingStatus'
powerloom_broadcast_id_zset = 'powerloom:broadcastID:' + settings.NAMESPACE + ':broadcastProcessingStatus'
polymarket_queued_trade_vol_epochs_redis_q_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:queuedTradeVolumeEpochs'
polymarket_seed_liquidity_lock = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:liquidity:Lock'
polymarket_base_liquidity_key_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:LiquidityBase'
polymarket_consolidated_liquidity_key_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:consolidatedLiquidity'
position_id_cache_key_prefix_f = 'polymarket:market:'+settings.NAMESPACE+':{}:outcome:'  # market_id
eth_log_request_data_f = 'powerloom:ethLogs:'+settings.NAMESPACE+':requestId:{}:results'  # request UUID
