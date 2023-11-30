import asyncio
import json
import os
from typing import List

import tenacity
from ipfs_client.dag import IPFSAsyncClientError
from redis import asyncio as aioredis
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential

from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import logger
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.file_utils import write_json_file
from snapshotter.utils.models.data_models import ProjectStatus
from snapshotter.utils.models.data_models import SnapshotterIncorrectSnapshotSubmission
from snapshotter.utils.models.data_models import SnapshotterMissedSnapshotSubmission
from snapshotter.utils.models.data_models import SnapshotterProjectStatus
from snapshotter.utils.models.data_models import SnapshotterReportState
from snapshotter.utils.models.data_models import SnapshotterStatus
from snapshotter.utils.models.data_models import SnapshotterStatusReport
from snapshotter.utils.redis.redis_keys import project_finalized_data_zset
from snapshotter.utils.redis.redis_keys import project_first_epoch_hmap
from snapshotter.utils.redis.redis_keys import project_snapshotter_status_report_key
from snapshotter.utils.redis.redis_keys import source_chain_block_time_key
from snapshotter.utils.redis.redis_keys import source_chain_epoch_size_key
from snapshotter.utils.redis.redis_keys import source_chain_id_key
from snapshotter.utils.rpc import get_event_sig_and_abi

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
async def get_project_finalized_cid(redis_conn: aioredis.Redis, state_contract_obj, rpc_helper, epoch_id, project_id):
    """
    Get the CID of the finalized data for a given project and epoch.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.
        state_contract_obj: Contract object for the state contract.
        rpc_helper: Helper object for making RPC calls.
        epoch_id (int): Epoch ID for which to get the CID.
        project_id (str): ID of the project for which to get the CID.

    Returns:
        str: CID of the finalized data for the given project and epoch, or None if not found.
    """

    project_first_epoch = await get_project_first_epoch(
        redis_conn, state_contract_obj, rpc_helper, project_id,
    )
    if epoch_id < project_first_epoch:
        return None

    # if data is present in finalzied data zset, return it
    cid_data = await redis_conn.zrangebyscore(
        project_finalized_data_zset(project_id),
        epoch_id,
        epoch_id,
    )
    if cid_data:
        cid = cid_data[0].decode('utf-8')
    else:
        cid, _ = await w3_get_and_cache_finalized_cid(redis_conn, state_contract_obj, rpc_helper, epoch_id, project_id)

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
    redis_conn: aioredis.Redis,
    state_contract_obj,
    rpc_helper,
    epoch_id,
    project_id,
):
    """
    This function retrieves the consensus status and the max snapshot CID for a given project and epoch.
    If the consensus status is True, the CID is added to a Redis sorted set with the epoch ID as the score.
    If the consensus status is False, a null value is added to the sorted set with the epoch ID as the score.

    Args:
        redis_conn (aioredis.Redis): Redis connection object
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

    [consensus_status, cid] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)
    logger.trace(f'consensus status for project {project_id} and epoch {epoch_id} is {consensus_status}')
    if consensus_status[0]:
        await redis_conn.zadd(
            project_finalized_data_zset(project_id),
            {cid: epoch_id},
        )
        return cid, epoch_id
    else:
        # Add null to zset
        await redis_conn.zadd(
            project_finalized_data_zset(project_id),
            {f'null_{epoch_id}': epoch_id},
        )
        return f'null_{epoch_id}', epoch_id


# TODO: warmup cache to reduce RPC calls overhead
async def get_project_first_epoch(redis_conn: aioredis.Redis, state_contract_obj, rpc_helper, project_id):
    """
    Get the first epoch for a given project ID.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.
        state_contract_obj: Contract object for the state contract.
        rpc_helper: RPC helper object.
        project_id (str): ID of the project.

    Returns:
        int: The first epoch for the given project ID.
    """
    first_epoch_data = await redis_conn.hget(
        project_first_epoch_hmap(),
        project_id,
    )
    if first_epoch_data:
        first_epoch = int(first_epoch_data)
        return first_epoch
    else:
        tasks = [
            state_contract_obj.functions.projectFirstEpochId(project_id),
        ]

        [first_epoch] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)
        logger.info(f'first epoch for project {project_id} is {first_epoch}')
        # Don't cache if it is 0
        if first_epoch == 0:
            return 0

        await redis_conn.hset(
            project_first_epoch_hmap(),
            project_id,
            first_epoch,
        )

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


async def get_submission_data(redis_conn: aioredis.Redis, cid, ipfs_reader, project_id: str) -> dict:
    """
    Fetches submission data from cache or IPFS.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.
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

    cached_data_path = os.path.join(settings.ipfs.local_cache_path, project_id, 'snapshots')
    filename = f'{cid}.json'
    try:
        submission_data = read_json_file(os.path.join(cached_data_path, filename))
    except Exception as e:
        # Fetch from IPFS
        logger.trace('Error while reading from cache', error=e)
        logger.info('Project {} CID {}, fetching data from IPFS', project_id, cid)
        try:
            submission_data = await fetch_file_from_ipfs(ipfs_reader, cid)
        except:
            logger.error('Error while fetching data from IPFS | Project {} | CID {}', project_id, cid)
            submission_data = dict()
        else:
            # Cache it
            write_json_file(cached_data_path, filename, submission_data)
            submission_data = json.loads(submission_data)
    return submission_data


async def get_submission_data_bulk(
    redis_conn: aioredis.Redis,
    cids: List[str],
    ipfs_reader,
    project_ids: List[str],
) -> List[dict]:
    """
    Retrieves submission data for multiple submissions in bulk.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.
        cids (List[str]): List of submission CIDs.
        ipfs_reader: IPFS reader object.
        project_ids (List[str]): List of project IDs.

    Returns:
        List[dict]: List of submission data dictionaries.
    """
    batch_size = 10
    all_snapshot_data = []
    for i in range(0, len(cids), batch_size):
        batch_cids = cids[i:i + batch_size]
        batch_project_ids = project_ids[i:i + batch_size]
        batch_snapshot_data = await asyncio.gather(
            *[
                get_submission_data(redis_conn, cid, ipfs_reader, project_id)
                for cid, project_id in zip(batch_cids, batch_project_ids)
            ],
        )
        all_snapshot_data.extend(batch_snapshot_data)

    return all_snapshot_data


async def get_project_epoch_snapshot(
    redis_conn: aioredis.Redis, state_contract_obj, rpc_helper, ipfs_reader, epoch_id, project_id,
) -> dict:
    """
    Retrieves the epoch snapshot for a given project.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.
        state_contract_obj: State contract object.
        rpc_helper: RPC helper object.
        ipfs_reader: IPFS reader object.
        epoch_id (int): Epoch ID.
        project_id (str): Project ID.

    Returns:
        dict: The epoch snapshot data.
    """
    cid = await get_project_finalized_cid(redis_conn, state_contract_obj, rpc_helper, epoch_id, project_id)
    if cid:
        data = await get_submission_data(redis_conn, cid, ipfs_reader, project_id)
        return data
    else:
        return dict()


async def get_source_chain_id(redis_conn: aioredis.Redis, state_contract_obj, rpc_helper):
    """
    Retrieves the source chain ID from Redis cache if available, otherwise fetches it from the state contract and caches it in Redis.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.
        state_contract_obj: State contract object.
        rpc_helper: RPC helper object.

    Returns:
        int: The source chain ID.
    """
    source_chain_id_data = await redis_conn.get(
        source_chain_id_key(),
    )
    if source_chain_id_data:
        source_chain_id = int(source_chain_id_data.decode('utf-8'))
        return source_chain_id
    else:
        tasks = [
            state_contract_obj.functions.SOURCE_CHAIN_ID(),
        ]

        [source_chain_id] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)

        await redis_conn.set(
            source_chain_id_key(),
            source_chain_id,
        )
        return source_chain_id


async def build_projects_list_from_events(redis_conn: aioredis.Redis, state_contract_obj, rpc_helper):
    """
    Builds a list of project IDs from the 'ProjectsUpdated' events emitted by the state contract.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.
        state_contract_obj: Contract object of the state contract.
        rpc_helper: Helper object for making RPC calls.

    Returns:
        list: List of project IDs.
    """
    EVENT_SIGS = {
        'ProjectsUpdated': 'ProjectsUpdated(string,bool,uint256)',
    }

    EVENT_ABI = {
        'ProjectsUpdated': state_contract_obj.events.ProjectsUpdated._get_event_abi(),
    }

    [start_block] = await rpc_helper.web3_call(
        [state_contract_obj.functions.DeploymentBlockNumber()],
        redis_conn=redis_conn,
    )

    current_block = await rpc_helper.get_current_block_number(redis_conn)
    event_sig, event_abi = get_event_sig_and_abi(EVENT_SIGS, EVENT_ABI)

    # from start_block to current block, get all events in batches of 1000, 10 requests parallelly
    request_task_batch_size = 10
    project_updates = set()
    for cumulative_block_range in range(start_block, current_block, 1000 * request_task_batch_size):
        # split into 10 requests
        tasks = []
        for block_range in range(
            cumulative_block_range,
            min(current_block, cumulative_block_range + 1000 * request_task_batch_size),
            1000,
        ):
            tasks.append(
                rpc_helper.get_events_logs(
                    **{
                        'contract_address': state_contract_obj.address,
                        'to_block': min(current_block, block_range + 1000),
                        'from_block': block_range,
                        'topics': [event_sig],
                        'event_abi': event_abi,
                        'redis_conn': redis_conn,
                    },
                ),
            )

        block_range_event_logs = await asyncio.gather(*tasks)

        for event_logs in block_range_event_logs:
            for event_log in event_logs:
                if event_log.args.allowed:
                    project_updates.add(event_log.args.projectId)
                else:
                    project_updates.discard(event_log.args.projectId)

    return list(project_updates)


async def get_projects_list(redis_conn: aioredis.Redis, state_contract_obj, rpc_helper):
    """
    Fetches the list of projects from the state contract.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.
        state_contract_obj: Contract object for the state contract.
        rpc_helper: RPC helper object.

    Returns:
        List: List of projects.
    """
    try:
        tasks = [
            state_contract_obj.functions.getProjects(),
        ]

        [projects_list] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)
        return projects_list

    except Exception as e:
        logger.warning('Error while fetching projects list from contract', error=e)
        return []


async def get_snapshot_submision_window(redis_conn: aioredis.Redis, state_contract_obj, rpc_helper):
    """
    Get the snapshot submission window from the state contract.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.
        state_contract_obj: State contract object.
        rpc_helper: RPC helper object.

    Returns:
        submission_window (int): The snapshot submission window.
    """
    tasks = [
        state_contract_obj.functions.snapshotSubmissionWindow(),
    ]

    [submission_window] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)

    return submission_window


async def get_source_chain_epoch_size(redis_conn: aioredis.Redis, state_contract_obj, rpc_helper):
    """
    This function retrieves the epoch size of the source chain from the state contract.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.
        state_contract_obj: Contract object for the state contract.
        rpc_helper: Helper object for making RPC calls.

    Returns:
        int: The epoch size of the source chain.
    """
    source_chain_epoch_size_data = await redis_conn.get(
        source_chain_epoch_size_key(),
    )
    if source_chain_epoch_size_data:
        source_chain_epoch_size = int(source_chain_epoch_size_data.decode('utf-8'))
        return source_chain_epoch_size
    else:
        tasks = [
            state_contract_obj.functions.EPOCH_SIZE(),
        ]

        [source_chain_epoch_size] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)

        await redis_conn.set(
            source_chain_epoch_size_key(),
            source_chain_epoch_size,
        )

        return source_chain_epoch_size


async def get_source_chain_block_time(redis_conn: aioredis.Redis, state_contract_obj, rpc_helper):
    """
    Get the block time of the source chain.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.
        state_contract_obj: Contract object for the state contract.
        rpc_helper: RPC helper object.

    Returns:
        int: Block time of the source chain.
    """
    source_chain_block_time_data = await redis_conn.get(
        source_chain_block_time_key(),
    )
    if source_chain_block_time_data:
        source_chain_block_time = int(source_chain_block_time_data.decode('utf-8'))
        return source_chain_block_time
    else:
        tasks = [
            state_contract_obj.functions.SOURCE_CHAIN_BLOCK_TIME(),
        ]

        [source_chain_block_time] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)
        source_chain_block_time = int(source_chain_block_time / 1e4)

        await redis_conn.set(
            source_chain_block_time_key(),
            source_chain_block_time,
        )

        return source_chain_block_time


async def get_tail_epoch_id(
        redis_conn: aioredis.Redis,
        state_contract_obj,
        rpc_helper,
        current_epoch_id,
        time_in_seconds,
        project_id,
):
    """
    Returns the tail epoch_id and a boolean indicating if tail contains the full time window.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.
        state_contract_obj: State contract object.
        rpc_helper: RPC helper object.
        current_epoch_id (int): Current epoch ID.
        time_in_seconds (int): Time in seconds.
        project_id (str): Project ID.

    Returns:
        Tuple[int, bool]: Tail epoch ID and a boolean indicating if tail contains the full time window.
    """
    source_chain_epoch_size = await get_source_chain_epoch_size(redis_conn, state_contract_obj, rpc_helper)
    source_chain_block_time = await get_source_chain_block_time(redis_conn, state_contract_obj, rpc_helper)

    # calculate tail epoch_id
    tail_epoch_id = current_epoch_id - int(time_in_seconds / (source_chain_epoch_size * source_chain_block_time))
    project_first_epoch = await(
        get_project_first_epoch(redis_conn, state_contract_obj, rpc_helper, project_id)
    )
    if tail_epoch_id < project_first_epoch:
        tail_epoch_id = project_first_epoch
        return tail_epoch_id, True

    logger.trace(
        'project ID {} tail epoch_id: {} against head epoch ID {} ',
        project_id, tail_epoch_id, current_epoch_id,
    )

    return tail_epoch_id, False


async def get_project_epoch_snapshot_bulk(
        redis_conn: aioredis.Redis,
        state_contract_obj,
        rpc_helper,
        ipfs_reader,
        epoch_id_min: int,
        epoch_id_max: int,
        project_id,
):
    """
    Fetches the snapshot data for a given project and epoch range.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.
        state_contract_obj: State contract object.
        rpc_helper: RPC helper object.
        ipfs_reader: IPFS reader object.
        epoch_id_min (int): Minimum epoch ID to fetch snapshot data for.
        epoch_id_max (int): Maximum epoch ID to fetch snapshot data for.
        project_id: ID of the project to fetch snapshot data for.

    Returns:
        A list of snapshot data for the given project and epoch range.
    """
    batch_size = 100

    project_first_epoch = await get_project_first_epoch(
        redis_conn, state_contract_obj, rpc_helper, project_id,
    )
    if epoch_id_min < project_first_epoch:
        epoch_id_min = project_first_epoch

    # if data is present in finalzied data zset, return it
    cid_data_with_epochs = await redis_conn.zrangebyscore(
        project_finalized_data_zset(project_id),
        epoch_id_min,
        epoch_id_max,
        withscores=True,
    )

    cid_data_with_epochs = [(cid.decode('utf-8'), int(epoch_id)) for cid, epoch_id in cid_data_with_epochs]

    all_epochs = set(range(epoch_id_min, epoch_id_max + 1))

    missing_epochs = list(all_epochs.difference(set([epoch_id for _, epoch_id in cid_data_with_epochs])))
    if missing_epochs:
        logger.info('found {} missing_epochs, fetching from contract', len(missing_epochs))

    for i in range(0, len(missing_epochs), batch_size):

        tasks = [
            get_project_finalized_cid(
                redis_conn, state_contract_obj, rpc_helper, epoch_id, project_id,
            ) for epoch_id in missing_epochs[i:i + batch_size]
        ]

        batch_cid_data_with_epochs = list(zip(await asyncio.gather(*tasks), missing_epochs))

        cid_data_with_epochs += batch_cid_data_with_epochs

    valid_cid_data_with_epochs = []
    for cid, epoch_id in cid_data_with_epochs:
        if cid and 'null' not in cid:
            valid_cid_data_with_epochs.append((cid, epoch_id))

    all_snapshot_data = await get_submission_data_bulk(
        redis_conn, [cid for cid, _ in valid_cid_data_with_epochs], ipfs_reader, [
            project_id,
        ] * len(valid_cid_data_with_epochs),
    )

    return all_snapshot_data


async def get_snapshotter_status(redis_conn: aioredis.Redis):
    """
    Returns the snapshotter status for all projects.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.

    Returns:
        SnapshotterStatus: Object containing the snapshotter status for all projects.
    """
    status_keys = []

    all_projects = await redis_conn.smembers('storedProjectIds')
    all_projects = [project_id.decode('utf-8') for project_id in all_projects]

    for project_id in all_projects:
        status_keys.append(f'projectID:{project_id}:totalSuccessfulSnapshotCount')
        status_keys.append(f'projectID:{project_id}:totalIncorrectSnapshotCount')
        status_keys.append(f'projectID:{project_id}:totalMissedSnapshotCount')

    all_projects_status = await redis_conn.mget(status_keys)

    total_successful_submissions = 0
    total_incorrect_submissions = 0
    total_missed_submissions = 0
    overall_status = SnapshotterStatus(projects=[])

    # project level data
    project_index = 0
    successful_submissions = 0
    incorrect_submissions = 0
    missed_submissions = 0

    for index, count in enumerate(all_projects_status):
        if count is None:
            count = 0

        # as each project has three counts viz. successful, incorrect and missed
        if index % 3 == 0:
            successful_submissions = int(count)
            total_successful_submissions += int(count)
        elif index % 3 == 1:
            incorrect_submissions = int(count)
            total_incorrect_submissions += int(count)
        else:
            missed_submissions = int(count)
            total_missed_submissions += int(count)
            overall_status.projects.append(
                ProjectStatus(
                    projectId=all_projects[project_index],
                    successfulSubmissions=successful_submissions,
                    incorrectSubmissions=incorrect_submissions,
                    missedSubmissions=missed_submissions,
                ),
            )
            project_index += 1

    overall_status.totalSuccessfulSubmissions = total_successful_submissions
    overall_status.totalIncorrectSubmissions = total_incorrect_submissions
    overall_status.totalMissedSubmissions = total_missed_submissions

    return overall_status


async def get_snapshotter_project_status(redis_conn: aioredis.Redis, project_id: str, with_data: bool):
    """
    Retrieves the snapshotter project status for a given project ID.

    Args:
        redis_conn (aioredis.Redis): Redis connection object.
        project_id (str): ID of the project to retrieve the status for.
        with_data (bool): Whether to include snapshot data in the response.

    Returns:
        SnapshotterProjectStatus: Object containing the project status.
    """
    reports = await redis_conn.hgetall(project_snapshotter_status_report_key(project_id))

    reports = {
        int(k.decode('utf-8')): SnapshotterStatusReport.parse_raw(v.decode('utf-8'))
        for k, v in reports.items()
    }

    project_status = SnapshotterProjectStatus(missedSubmissions=[], incorrectSubmissions=[])

    for epoch_id, report in reports.items():
        if report.state is SnapshotterReportState.MISSED_SNAPSHOT:
            project_status.missedSubmissions.append(
                SnapshotterMissedSnapshotSubmission(
                    epochId=epoch_id,
                    reason=report.reason,
                    finalizedSnapshotCid=report.finalizedSnapshotCid,
                ),
            )
        elif report.state is SnapshotterReportState.SUBMITTED_INCORRECT_SNAPSHOT:
            project_status.incorrectSubmissions.append(
                SnapshotterIncorrectSnapshotSubmission(
                    epochId=epoch_id,
                    reason=report.reason,
                    submittedSnapshotCid=report.submittedSnapshotCid,
                    submittedSnapshot=report.submittedSnapshot if with_data else None,
                    finalizedSnapshotCid=report.finalizedSnapshotCid,
                    finalizedSnapshot=report.finalizedSnapshot if with_data else None,
                ),
            )

    return project_status
