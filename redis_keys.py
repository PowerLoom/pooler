from dynaconf import settings

polymarket_base_trade_vol_key_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:TradeVolumeBase'
polymarket_consolidated_trade_vol_key_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:consolidatedTradeVolume'
polymarket_queued_trade_vol_epochs_zset_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:queuedTradeVolumeEpochs'
polymarket_trade_vol_epoch_details_hset_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:tradeVolumeEpochs'
polymarket_seed_trade_lock = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:tradeVolume:Lock'
polymarket_market_trades_processing_status = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:tradesProcessingStatus'
powerloom_broadcast_id_processing_set = 'polymarket:broadcastID:' + settings.NAMESPACE + ':{}:broadcastProcessingStatus'
powerloom_broadcast_id_zset = 'powerloom:broadcastID:' + settings.NAMESPACE + ':broadcastProcessingStatus'
polymarket_queued_trade_vol_epochs_redis_q_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:queuedTradeVolumeEpochs'
polymarket_failed_trade_vol_epochs_redis_q_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:failedTradeVolumeEpochs'
polymarket_seed_liquidity_lock = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:liquidity:Lock'
polymarket_base_liquidity_key_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:LiquidityBase'
polymarket_consolidated_liquidity_key_f = 'polymarket:marketMaker:'+settings.NAMESPACE+':{}:consolidatedLiquidity'
position_id_cache_key_prefix_f = 'polymarket:market:'+settings.NAMESPACE+':{}:outcome:'  # market_id
eth_log_request_data_f = 'powerloom:ethLogs:'+settings.NAMESPACE+':requestId:{}:results'  # request UUID
