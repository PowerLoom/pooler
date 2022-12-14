from dynaconf import settings
uniswap_failed_query_pair_total_reserves_epochs_redis_q_f = 'uniswap:pairContract:' + settings.NAMESPACE + ':{}:failedQueryPairTotalReservesEpochs'
uniswap_discarded_query_pair_total_reserves_epochs_redis_q_f = 'uniswap:pairContract:' + settings.NAMESPACE + ':{}:discardedQueryPairTotalReservesEpochs'
uniswap_failed_query_pair_trade_volume_epochs_redis_q_f = 'uniswap:pairContract:' + settings.NAMESPACE + ':{}:failedQueryPairTradeVolumeEpochs'
uniswap_discarded_query_pair_trade_volume_epochs_redis_q_f = 'uniswap:pairContract:' + settings.NAMESPACE + ':{}:discardedQueryPairTradeVolumeEpochs'
uniswap_failed_commit_pair_trade_volume_epochs_redis_q_f = 'uniswap:pairContract:' + settings.NAMESPACE + ':{}:failedCommitPairTradeVolumeEpochs'
uniswap_failed_commit_pair_total_reserves_epochs_redis_q_f = 'uniswap:pairContract:' + settings.NAMESPACE + ':{}:failedCommitPairTotalReservesEpochs'
uniswap_pair_total_reserves_processing_status = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:PairTotalReservesProcessingStatus'
uniswap_pair_contract_tokens_addresses = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:PairContractTokensAddresses'
uniswap_pair_contract_tokens_data = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:PairContractTokensData'
uniswap_pair_total_reserves_last_snapshot = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:LastCachedPairReserve'
uniswap_pair_cached_token_price = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:cachedPairPrice'
uniswap_pair_contract_V2_pair_data = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:contractV2PairCachedData'
uniswap_V2_summarized_snapshots_zset = 'uniswap:V2PairsSummarySnapshot:'+settings.NAMESPACE+':snapshotsZset'
uniswap_V2_snapshot_at_blockheight = 'uniswap:V2PairsSummarySnapshot:'+settings.NAMESPACE+':snapshot:{}'  # block_height
uniswap_v2_daily_stats_snapshot_zset = 'uniswap:V2DailyStatsSnapshot:'+settings.NAMESPACE+':snapshotsZset'
uniswap_V2_daily_stats_at_blockheight = 'uniswap:V2DailyStatsSnapshot:'+settings.NAMESPACE+':snapshot:{}'  # block_height
uniswap_v2_tokens_snapshot_zset = 'uniswap:V2TokensSummarySnapshot:'+settings.NAMESPACE+':snapshotsZset'
uniswap_V2_tokens_at_blockheight = 'uniswap:V2TokensSummarySnapshot:'+settings.NAMESPACE+':{}'  # block_height
uniswap_cb_broadcast_processing_logs_zset = 'uniswap:broadcastID:' + settings.NAMESPACE + ':{}:processLogs'
uniswap_pair_cached_recent_logs = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:recentLogs'
uniswap_projects_dag_verifier_status = "projects:"+settings.NAMESPACE+":dagVerificationStatus"
uniswap_eth_usd_price_zset = "uniswap:ethBlockHeightPrice:"+settings.NAMESPACE+":ethPriceZset"
uniswap_tokens_pair_map = "uniswap:pairContract:"+settings.NAMESPACE+":tokensPairMap"
uniswap_pair_tentative_block_height = "projectID:uniswap_pairContract_trade_volume_{}_"+settings.NAMESPACE+":tentativeBlockHeight"
uniswap_pair_block_height = "projectID:uniswap_pairContract_trade_volume_{}_"+settings.NAMESPACE+":blockHeight"
uniswap_pair_cached_block_height_token_price = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:cachedPairBlockHeightTokenPrice'
cached_block_details_at_height = 'uniswap:blockDetail:'+settings.NAMESPACE+':blockDetailZset'
uniswap_pair_hits_payload_data_key = 'hitsPayloadData'
powerloom_broadcast_id_zset = 'powerloom:broadcastID:' + settings.NAMESPACE + ':broadcastProcessingStatus'
