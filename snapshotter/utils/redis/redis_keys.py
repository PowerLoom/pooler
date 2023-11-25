from snapshotter.settings.config import settings

cached_block_details_at_height = (
    'uniswap:blockDetail:' + settings.namespace + ':blockDetailZset'
)

epoch_detector_last_processed_epoch = 'SystemEpochDetector:lastProcessedEpoch'

event_detector_last_processed_block = 'SystemEventDetector:lastProcessedBlock'

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

rpc_get_block_number_calls = (
    'rpc:blockNumber:' + settings.namespace + ':calls'
)

rpc_get_transaction_receipt_calls = (
    'rpc:transactionReceipt:' + settings.namespace + ':calls'
)

epoch_process_report_cached_key = 'epochProcessReport'

snapshot_submission_window_key = 'snapshotSubmissionWindow'

active_status_key = f'snapshotterActiveStatus:{settings.namespace}'

# project finalzed data zset


def project_finalized_data_zset(project_id):
    return f'projectID:{project_id}:finalizedData'


# project first epoch hashmap


def project_first_epoch_hmap():
    return 'projectFirstEpoch'


def source_chain_id_key():
    return 'sourceChainId'


def source_chain_block_time_key():
    return 'sourceChainBlockTime'


def source_chain_epoch_size_key():
    return 'sourceChainEpochSize'


def project_last_finalized_epoch_key(project_id):
    return f'projectID:{project_id}:lastFinalizedEpoch'


def project_successful_snapshot_submissions_suffix():
    return 'totalSuccessfulSnapshotCount'


def project_incorrect_snapshot_submissions_suffix():
    return 'totalIncorrectSnapshotCount'


def project_missed_snapshot_submissions_suffix():
    return 'totalMissedSnapshotCount'


def project_snapshotter_status_report_key(project_id):
    return f'projectID:{project_id}:snapshotterStatusReport'


def stored_projects_key():
    return 'storedProjectIds'


def epoch_txs_htable(epoch_id):
    return f'epochID:{epoch_id}:txReceipts'


def epoch_id_epoch_released_key(epoch_id):
    return f'epochID:{epoch_id}:epochReleased'


def epoch_id_project_to_state_mapping(epoch_id, state_id):
    return f'epochID:{epoch_id}:stateID:{state_id}:processingStatus'


def last_snapshot_processing_complete_timestamp_key():
    return f'lastSnapshotProcessingCompleteTimestamp:{settings.namespace}'


def last_epoch_detected_timestamp_key():
    return f'lastEpochDetectedTimestamp:{settings.namespace}'


def submitted_base_snapshots_key(epoch_id, project_id):
    return f'submittedBaseSnapshots:{epoch_id}:{project_id}'


def submitted_unfinalized_snapshot_cids(project_id):
    return f'projectID:{project_id}:unfinalizedSnapshots'


def process_hub_core_start_timestamp():
    return f'processHubCoreStartTimestamp:{settings.namespace}'
