from pooler.settings.config import settings

uniswap_failed_query_pair_total_reserves_epochs_redis_q_f = (
    'uniswap:pairContract:' +
    settings.namespace +
    ':{}:failedQueryPairTotalReservesEpochs'
)
uniswap_discarded_query_pair_total_reserves_epochs_redis_q_f = (
    'uniswap:pairContract:' +
    settings.namespace +
    ':{}:discardedQueryPairTotalReservesEpochs'
)
uniswap_failed_query_pair_trade_volume_epochs_redis_q_f = (
    'uniswap:pairContract:' +
    settings.namespace +
    ':{}:failedQueryPairTradeVolumeEpochs'
)
uniswap_discarded_query_pair_trade_volume_epochs_redis_q_f = (
    'uniswap:pairContract:' +
    settings.namespace +
    ':{}:discardedQueryPairTradeVolumeEpochs'
)
uniswap_failed_commit_pair_trade_volume_epochs_redis_q_f = (
    'uniswap:pairContract:' +
    settings.namespace +
    ':{}:failedCommitPairTradeVolumeEpochs'
)
uniswap_failed_commit_pair_total_reserves_epochs_redis_q_f = (
    'uniswap:pairContract:' +
    settings.namespace +
    ':{}:failedCommitPairTotalReservesEpochs'
)
uniswap_pair_total_reserves_processing_status = (
    'uniswap:pairContract:' +
    settings.namespace +
    ':{}:PairTotalReservesProcessingStatus'
)
uniswap_pair_contract_tokens_addresses = (
    'uniswap:pairContract:' + settings.namespace + ':{}:PairContractTokensAddresses'
)
uniswap_pair_contract_tokens_data = (
    'uniswap:pairContract:' + settings.namespace + ':{}:PairContractTokensData'
)
uniswap_pair_total_reserves_last_snapshot = (
    'uniswap:pairContract:' + settings.namespace + ':{}:LastCachedPairReserve'
)
uniswap_pair_cached_token_price = (
    'uniswap:pairContract:' + settings.namespace + ':{}:cachedPairPrice'
)
uniswap_pair_contract_V2_pair_data = (
    'uniswap:pairContract:' + settings.namespace + ':{}:contractV2PairCachedData'
)
uniswap_V2_summarized_snapshots_zset = (
    'uniswap:V2PairsSummarySnapshot:' + settings.namespace + ':snapshotsZset'
)
uniswap_V2_snapshot_at_blockheight = (
    'uniswap:V2PairsSummarySnapshot:' + settings.namespace + ':snapshot:{}'
)  # block_height
uniswap_v2_daily_stats_snapshot_zset = (
    'uniswap:V2DailyStatsSnapshot:' + settings.namespace + ':snapshotsZset'
)
uniswap_V2_daily_stats_at_blockheight = (
    'uniswap:V2DailyStatsSnapshot:' + settings.namespace + ':snapshot:{}'
)  # block_height
uniswap_v2_tokens_snapshot_zset = (
    'uniswap:V2TokensSummarySnapshot:' + settings.namespace + ':snapshotsZset'
)
uniswap_V2_tokens_at_blockheight = (
    'uniswap:V2TokensSummarySnapshot:' + settings.namespace + ':{}'
)  # block_height
uniswap_cb_broadcast_processing_logs_zset = (
    'uniswap:broadcastID:' + settings.namespace + ':{}:processLogs'
)
uniswap_pair_cached_recent_logs = (
    'uniswap:pairContract:' + settings.namespace + ':{}:recentLogs'
)
uniswap_projects_dag_verifier_status = (
    'projects:' + settings.namespace + ':dagVerificationStatus'
)
uniswap_eth_usd_price_zset = (
    'uniswap:ethBlockHeightPrice:' + settings.namespace + ':ethPriceZset'
)
uniswap_tokens_pair_map = (
    'uniswap:pairContract:' + settings.namespace + ':tokensPairMap'
)
uniswap_pair_tentative_block_height = (
    'projectID:uniswap_pairContract_trade_volume_{}_' +
    settings.namespace +
    ':tentativeBlockHeight'
)
uniswap_pair_block_height = (
    'projectID:uniswap_pairContract_trade_volume_{}_' +
    settings.namespace +
    ':blockHeight'
)
uniswap_pair_cached_block_height_token_price = (
    'uniswap:pairContract:' + settings.namespace +
    ':{}:cachedPairBlockHeightTokenPrice'
)
cached_block_details_at_height = (
    'uniswap:blockDetail:' + settings.namespace + ':blockDetailZset'
)
uniswap_pair_hits_payload_data_key = 'hitsPayloadData'
powerloom_broadcast_id_zset = (
    'powerloom:broadcastID:' + settings.namespace + ':broadcastProcessingStatus'
)
epoch_detector_last_processed_epoch = 'SystemEpochDetector:lastProcessedEpoch'
