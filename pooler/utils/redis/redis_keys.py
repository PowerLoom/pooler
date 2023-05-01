from pooler.settings.config import settings

failed_query_epochs_redis_q = (
    'failedQueryEpochs:' + settings.namespace +
    ':{}:{}'
)

discarded_query_epochs_redis_q = (
    'discardedQueryEpochs:' + settings.namespace +
    ':{}:{}'
)

failed_commit_epochs_redis_q = (
    'failedCommitEpochs:' + settings.namespace +
    ':{}:{}'
)

cb_broadcast_processing_logs_zset = (
    'broadcastID:' + settings.namespace + ':{}:processLogs'
)

cached_block_details_at_height = (
    'uniswap:blockDetail:' + settings.namespace + ':blockDetailZset'
)
project_hits_payload_data_key = 'hitsPayloadData'
powerloom_broadcast_id_zset = (
    'powerloom:broadcastID:' + settings.namespace + ':broadcastProcessingStatus'
)
epoch_detector_last_processed_epoch = 'SystemEpochDetector:lastProcessedEpoch'

event_detector_last_processed_block = 'SystemEventDetector:lastProcessedBlock'

projects_dag_verifier_status = (
    'projects:' + settings.namespace + ':dagVerificationStatus'
)

uniswap_eth_usd_price_zset = (
    'uniswap:ethBlockHeightPrice:' + settings.namespace + ':ethPriceZset'
)

rpc_json_rpc_calls = (
    'rpc:jsonRpc:' + settings.namespace + ':calls'
)

rpc_get_event_logs_calls = (
    'rpc:eventLogsCount:' + settings.namespace + ':calls'
)

rpc_web3_calls = (
    'rpc:web3:' + settings.namespace + ':calls'
)

rpc_blocknumber_calls = (
    'rpc:blocknumber:' + settings.namespace + ':calls'
)


# project finalzed data zset
def get_project_finalized_data_zset(project_id):
    return f'projectID:{project_id}:finalizedData'

# project first epoch hashmap


def get_project_first_epoch_hmap():
    return 'projectFirstEpoch'


def get_cid_data(cid):
    return f'cidData:{cid}'


def get_project_epoch_size(project_id):
    return f'projectID:{project_id}:epochSize'


def get_last_aggregate_cache(project_id: str, aggregate_name: str, time_series_identifier: str):
    return f'projectID:{project_id}:{time_series_identifier}:{aggregate_name}:aggregateCache'
