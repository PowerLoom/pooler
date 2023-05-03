import asyncio
from typing import List

from redis import asyncio as aioredis
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential

from pooler.utils.default_logger import logger
from pooler.utils.ipfs_async import async_ipfs_client as ipfs_client
from pooler.utils.redis.redis_keys import cid_data
from pooler.utils.redis.redis_keys import project_finalized_data_zset
from pooler.utils.redis.redis_keys import project_first_epoch_hmap
from pooler.utils.redis.redis_keys import source_chain_block_time_key
from pooler.utils.redis.redis_keys import source_chain_epoch_size_key
from pooler.utils.redis.redis_keys import source_chain_id_key

logger = logger.bind(module='data_helper')


async def get_project_finalized_cid(redis_conn: aioredis.Redis, state_contract_obj, rpc_helper, epoch_id, project_id):

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
        cid = await check_and_get_finalized_cid(redis_conn, state_contract_obj, rpc_helper, epoch_id, project_id)

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
async def check_and_get_finalized_cid(redis_conn: aioredis.Redis, state_contract_obj, rpc_helper, epoch_id, project_id):

    tasks = [
        state_contract_obj.functions.snapshotStatus(project_id, epoch_id),
        state_contract_obj.functions.maxSnapshotsCid(project_id, epoch_id),
    ]

    [consensus_status, cid] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)
    logger.info(f'consensus status for project {project_id} and epoch {epoch_id} is {consensus_status}')
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
        return None, epoch_id


async def get_project_first_epoch(redis_conn: aioredis.Redis, state_contract_obj, rpc_helper, project_id):

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


async def get_submission_data(redis_conn: aioredis.Redis, cid):
    # TODO: Using redis for now, find better way to cache this data
    submission_data = await redis_conn.get(
        cid_data(cid),
    )
    if submission_data:
        return submission_data
    else:
        # Fetch from IPFS
        logger.info('CID {}, fetching data from IPFS', cid)
        submission_data = await ipfs_client.async_cat(cid)
        await redis_conn.set(
            cid_data(cid),
            submission_data,
        )

        return submission_data


@retry(
    reraise=True,
    retry=retry_if_exception_type(Exception),
    wait=wait_random_exponential(multiplier=1, max=10),
    stop=stop_after_attempt(3),
)
async def get_project_epoch_snapshot(redis_conn: aioredis.Redis, state_contract_obj, rpc_helper, epoch_id, project_id):
    cid = await get_project_finalized_cid(redis_conn, state_contract_obj, rpc_helper, epoch_id, project_id)
    if cid:
        data = await get_submission_data(redis_conn, cid)
        return data
    else:
        return None


async def get_source_chain_id(redis_conn: aioredis.Redis, state_contract_obj, rpc_helper):

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


async def get_source_chain_epoch_size(redis_conn: aioredis.Redis, state_contract_obj, rpc_helper):

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


# calculate tail epoch_id given current epoch and time in seconds
async def get_tail_epoch_id(
        redis_conn: aioredis.Redis,
        state_contract_obj,
        rpc_helper,
        current_epoch_id,
        time_in_seconds,
        project_id,
):
    # Returns tail epoch_id and a boolean indicating if tail contains the full time window
    source_chain_epoch_size = await get_source_chain_epoch_size(redis_conn, state_contract_obj, rpc_helper)
    source_chain_block_time = await get_source_chain_block_time(redis_conn, state_contract_obj, rpc_helper)

    # calculate tail epoch_id
    tail_epoch_id = current_epoch_id - int(time_in_seconds / (source_chain_epoch_size * source_chain_block_time))
    project_first_epoch = await(
        get_project_first_epoch(redis_conn, state_contract_obj, rpc_helper, project_id)
    )
    if tail_epoch_id < project_first_epoch:
        tail_epoch_id = project_first_epoch
        return tail_epoch_id, False

    logger.info('tail epoch_id: {}', tail_epoch_id)

    return tail_epoch_id, True

#


async def get_project_epoch_snapshot_bulk(
        redis_conn: aioredis.Redis,
        state_contract_obj,
        rpc_helper,
        epoch_id_min: int,
        epoch_id_max: int,
        project_id,
):

    batch_size = 100

    project_first_epoch = await get_project_first_epoch(
        redis_conn, state_contract_obj, rpc_helper, project_id,
    )
    if epoch_id_min < project_first_epoch:
        return None

    # if data is present in finalzied data zset, return it
    cid_data_with_epochs = await redis_conn.zrangebyscore(
        project_finalized_data_zset(project_id),
        epoch_id_min,
        epoch_id_max,
        withscores=True,
    )

    cid_data_with_epochs = [(cid.decode('utf-8'), int(epoch_id)) for cid, epoch_id in cid_data_with_epochs]

    all_epochs = set(range(epoch_id_min, epoch_id_max + 1))
    for cid, epoch_id in cid_data_with_epochs:
        all_epochs.remove(int(epoch_id))

    missing_epochs = list(all_epochs)
    if missing_epochs:
        logger.info('found {} missing_epochs, fetching from contract', len(missing_epochs))

    for i in range(0, len(missing_epochs), batch_size):

        tasks = [
            check_and_get_finalized_cid(
                redis_conn, state_contract_obj, rpc_helper, epoch_id, project_id,
            ) for epoch_id in missing_epochs[i:i + batch_size]
        ]

        batch_cid_data_with_epochs = await asyncio.gather(*tasks)

        cid_data_with_epochs += batch_cid_data_with_epochs

    valid_cid_data_with_epochs = []
    for data in cid_data_with_epochs:
        cid, epoch_id = data
        if cid and 'null' not in cid:
            valid_cid_data_with_epochs.append((cid, epoch_id))

    snapshot_data = await redis_conn.mget(
        *[
            cid_data(cid) for cid, _ in valid_cid_data_with_epochs
        ],
    )

    all_snapshot_data = []
    ipfs_snapshot_tasks = []
    logger.info('ipfs_snapshot_tasks: {}', len(ipfs_snapshot_tasks))

    for i in range(len(snapshot_data)):
        if snapshot_data[i]:
            all_snapshot_data.append(snapshot_data[i])
        else:
            ipfs_snapshot_tasks.append(get_submission_data(redis_conn, valid_cid_data_with_epochs[i][0]))

    ipfs_snapshot_data = await asyncio.gather(*ipfs_snapshot_tasks)
    all_snapshot_data.extend(ipfs_snapshot_data)
    logger.info('all_snapshot_data: {}', len(all_snapshot_data))
    return all_snapshot_data
