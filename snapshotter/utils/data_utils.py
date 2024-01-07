import json

import tenacity
from ipfs_client.dag import IPFSAsyncClientError
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential

from snapshotter.utils.default_logger import logger

logger = logger.bind(module='data_helper')


def retry_state_callback(retry_state: tenacity.RetryCallState):
    """
    Callback function to handle retry attempts for IPFS cat operation.

    Parameters:
    retry_state (tenacity.RetryCallState): The current state of the retry call.

    Returns:
    None
    """
    logger.warning(f'Encountered IPFS cat exception: {retry_state.outcome.exception()}')


# TODO: warmup cache to reduce RPC calls overhead
async def get_project_finalized_cid(state_contract_obj, rpc_helper, epoch_id, project_id):
    """
    Get the CID of the finalized data for a given project and epoch.

    Args:
        state_contract_obj: Contract object for the state contract.
        rpc_helper: Helper object for making RPC calls.
        epoch_id (int): Epoch ID for which to get the CID.
        project_id (str): ID of the project for which to get the CID.

    Returns:
        str: CID of the finalized data for the given project and epoch, or None if not found.
    """

    project_first_epoch = await get_project_first_epoch(
        state_contract_obj, rpc_helper, project_id,
    )
    if epoch_id < project_first_epoch:
        return None

    cid, _ = await w3_get_and_cache_finalized_cid(state_contract_obj, rpc_helper, epoch_id, project_id)

    if 'null' not in cid:
        return cid
    else:
        return None


@retry(
    reraise=True,
    retry=retry_if_exception_type(Exception),
    wait=wait_random_exponential(multiplier=1, max=10),
    stop=stop_after_attempt(3),
)
async def w3_get_and_cache_finalized_cid(
    state_contract_obj,
    rpc_helper,
    epoch_id,
    project_id,
):
    """
    This function retrieves the consensus status and the max snapshot CID for a given project and epoch.

    Args:
        state_contract_obj: Contract object for the state contract
        rpc_helper: Helper object for making web3 calls
        epoch_id (int): Epoch ID
        project_id (int): Project ID

    Returns:
        Tuple[str, int]: The CID and epoch ID if the consensus status is True, or the null value and epoch ID if the consensus status is False.
    """
    tasks = [
        state_contract_obj.functions.snapshotStatus(project_id, epoch_id),
        state_contract_obj.functions.maxSnapshotsCid(project_id, epoch_id),
    ]

    [consensus_status, cid] = await rpc_helper.web3_call(tasks)
    logger.trace(f'consensus status for project {project_id} and epoch {epoch_id} is {consensus_status}')
    if consensus_status[0]:
        return cid, epoch_id
    else:
        return f'null_{epoch_id}', epoch_id


async def get_project_last_finalized_cid_and_epoch(state_contract_obj, rpc_helper, project_id):
    """
    Get the last epoch for a given project ID.

    Args:
        state_contract_obj: Contract object for the state contract.
        rpc_helper: RPC helper object.
        project_id (str): ID of the project.

    Returns:
        int: The last epoch for the given project ID.
    """

    tasks = [
        state_contract_obj.functions.lastFinalizedSnapshot(project_id),
    ]

    [last_finalized_epoch] = await rpc_helper.web3_call(tasks)
    logger.info(f'last finalized epoch for project {project_id} is {last_finalized_epoch}')

    # getting finalized cid for last finalized epoch
    last_finalized_cid = await get_project_finalized_cid(
        state_contract_obj, rpc_helper, last_finalized_epoch, project_id,
    )

    if last_finalized_cid and 'null' not in last_finalized_cid:
        return last_finalized_cid, int(last_finalized_epoch)
    else:
        return '', 0


# TODO: warmup cache to reduce RPC calls overhead
async def get_project_first_epoch(state_contract_obj, rpc_helper, project_id):
    """
    Get the first epoch for a given project ID.

    Args:
        state_contract_obj: Contract object for the state contract.
        rpc_helper: RPC helper object.
        project_id (str): ID of the project.

    Returns:
        int: The first epoch for the given project ID.
    """
    tasks = [
        state_contract_obj.functions.projectFirstEpochId(project_id),
    ]

    [first_epoch] = await rpc_helper.web3_call(tasks)
    logger.info(f'first epoch for project {project_id} is {first_epoch}')
    # Don't cache if it is 0
    if first_epoch == 0:
        return 0

    return first_epoch


@retry(
    reraise=True,
    retry=retry_if_exception_type(IPFSAsyncClientError),
    wait=wait_random_exponential(multiplier=0.5, max=10),
    stop=stop_after_attempt(3),
    before_sleep=retry_state_callback,
)
async def fetch_file_from_ipfs(ipfs_reader, cid):
    """
    Fetches a file from IPFS using the given IPFS reader and CID.

    Args:
        ipfs_reader: An IPFS reader object.
        cid: The CID of the file to fetch.

    Returns:
        The contents of the file as bytes.
    """
    return await ipfs_reader.cat(cid)


async def get_submission_data(cid, ipfs_reader, project_id: str) -> dict:
    """
    Fetches submission data from cache or IPFS.

    Args:
        cid (str): IPFS content ID.
        ipfs_reader (ipfshttpclient.client.Client): IPFS client object.
        project_id (str): ID of the project.

    Returns:
        dict: Submission data.
    """
    if not cid:
        return dict()

    if 'null' in cid:
        return dict()

    logger.info('Project {} CID {}, fetching data from IPFS', project_id, cid)
    try:
        submission_data = await fetch_file_from_ipfs(ipfs_reader, cid)
    except:
        logger.error('Error while fetching data from IPFS | Project {} | CID {}', project_id, cid)
        submission_data = dict()
    else:
        submission_data = json.loads(submission_data)
    return submission_data


async def get_project_epoch_snapshot(
    state_contract_obj, rpc_helper, ipfs_reader, epoch_id, project_id,
) -> dict:
    """
    Retrieves the epoch snapshot for a given project.

    Args:
        state_contract_obj: State contract object.
        rpc_helper: RPC helper object.
        ipfs_reader: IPFS reader object.
        epoch_id (int): Epoch ID.
        project_id (str): Project ID.

    Returns:
        dict: The epoch snapshot data.
    """
    cid = await get_project_finalized_cid(state_contract_obj, rpc_helper, epoch_id, project_id)
    if cid:
        data = await get_submission_data(cid, ipfs_reader, project_id)
        return data
    else:
        return dict()


async def get_source_chain_id(state_contract_obj, rpc_helper):
    """
    Retrieves the source chain ID from the state contract.

    Args:
        state_contract_obj: State contract object.
        rpc_helper: RPC helper object.

    Returns:
        int: The source chain ID.
    """
    tasks = [
        state_contract_obj.functions.SOURCE_CHAIN_ID(),
    ]

    [source_chain_id] = await rpc_helper.web3_call(tasks)

    return source_chain_id


async def get_snapshot_submision_window(state_contract_obj, rpc_helper):
    """
    Get the snapshot submission window from the state contract.

    Args:
        state_contract_obj: State contract object.
        rpc_helper: RPC helper object.

    Returns:
        submission_window (int): The snapshot submission window.
    """
    tasks = [
        state_contract_obj.functions.snapshotSubmissionWindow(),
    ]

    [submission_window] = await rpc_helper.web3_call(tasks)

    return submission_window


async def get_source_chain_epoch_size(state_contract_obj, rpc_helper):
    """
    This function retrieves the epoch size of the source chain from the state contract.

    Args:
        state_contract_obj: Contract object for the state contract.
        rpc_helper: Helper object for making RPC calls.

    Returns:
        int: The epoch size of the source chain.
    """
    tasks = [
        state_contract_obj.functions.EPOCH_SIZE(),
    ]

    [source_chain_epoch_size] = await rpc_helper.web3_call(tasks)

    return source_chain_epoch_size


async def get_source_chain_block_time(state_contract_obj, rpc_helper):
    """
    Get the block time of the source chain.

    Args:
        state_contract_obj: Contract object for the state contract.
        rpc_helper: RPC helper object.

    Returns:
        int: Block time of the source chain.
    """
    tasks = [
        state_contract_obj.functions.SOURCE_CHAIN_BLOCK_TIME(),
    ]

    [source_chain_block_time] = await rpc_helper.web3_call(tasks)
    source_chain_block_time = int(source_chain_block_time / 1e4)

    return source_chain_block_time
