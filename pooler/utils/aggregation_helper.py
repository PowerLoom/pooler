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


async def get_project_finalized_cid(redis_conn: aioredis, state_contract_obj, rpc_helper, epochId, projectId):

    project_first_epoch = await get_project_first_epoch(redis_conn, state_contract_obj, rpc_helper, projectId)
    logger.info('First Project Epoch {} {}', epochId, project_first_epoch)
    if epochId < project_first_epoch:
        return None

    # if data is present in finalzied data zset, return it
    [cid] = await redis_conn.zrangebyscore(
        project_finalized_data_zset(projectId),
        epochId,
        epochId,
    )
    if cid:
        return cid.decode('utf-8')
    else:
        logger.info('CID not found in finalized data zset, fetching from contract')
        cid = await check_and_get_finalized_cid(redis_conn, state_contract_obj, rpc_helper, epochId, projectId)
        logger.info('CID {}', cid)
        return cid


async def check_and_get_finalized_cid(redis_conn: aioredis, state_contract_obj, rpc_helper, epochId, projectId):

    tasks = [
        state_contract_obj.functions.checkDynamicConsensusSnapshot(projectId, epochId),
        state_contract_obj.functions.maxSnapshotsCid(projectId, epochId),
    ]

    [consensus_status, cid] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)

    if consensus_status:
        await redis_conn.zadd(
            project_finalized_data_zset(projectId),
            epochId,
            cid,
        )
        return cid
    else:
        return None


async def get_project_first_epoch(redis_conn: aioredis, state_contract_obj, rpc_helper, projectId):
    first_epoch_data = await redis_conn.hget(
        project_first_epoch_hmap(),
        projectId,
    )
    if first_epoch_data:
        first_epoch = int(first_epoch_data)
        return first_epoch
    else:
        tasks = [
            state_contract_obj.functions.projectFirstEpochId(projectId),
        ]

        [first_epoch] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)

        await redis_conn.hset(
            project_first_epoch_hmap(),
            projectId,
            first_epoch,
        )

        return first_epoch


async def get_submission_data(redis_conn: aioredis, cid):
    # TODO: Using redis for now, find better way to cache this data
    logger.info('CID {}, fetching data from IPFS', cid)
    submission_data = await redis_conn.get(
        cid_data(cid),
    )
    if submission_data:
        logger.info('CID {}, found data in redis', cid)
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
async def get_project_epoch_snapshot(redis_conn: aioredis, state_contract_obj, rpc_helper, epochId, projectId):
    cid = await get_project_finalized_cid(redis_conn, state_contract_obj, rpc_helper, epochId, projectId)
    if cid:
        return await get_submission_data(redis_conn, cid)
    else:
        return None


async def get_source_chain_id(redis_conn: aioredis, state_contract_obj, rpc_helper):
    source_chain_id_data = await redis_conn.get(
        source_chain_id_key(),
    )
    if source_chain_id_data:
        source_chain_id = int(source_chain_id_data)
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


async def get_source_chain_epoch_size(redis_conn: aioredis, state_contract_obj, rpc_helper):
    source_chain_epoch_size_data = await redis_conn.get(
        source_chain_epoch_size_key(),
    )
    if source_chain_epoch_size_data:
        source_chain_epoch_size = int(source_chain_epoch_size_data)
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


async def get_source_chain_block_time(redis_conn: aioredis, state_contract_obj, rpc_helper):
    source_chain_block_time_data = await redis_conn.get(
        source_chain_block_time_key(),
    )
    if source_chain_block_time_data:
        source_chain_block_time = int(source_chain_block_time_data)
        return source_chain_block_time
    else:
        tasks = [
            state_contract_obj.functions.SOURCE_CHAIN_BLOCK_TIME(),
        ]

        [source_chain_block_time] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)
        source_chain_block_time = int(source_chain_block_time) / 1e4

        await redis_conn.set(
            source_chain_block_time_key(),
            source_chain_block_time,
        )

        return source_chain_block_time


# calculate tail epochId given current epoch and time in seconds
async def get_tail_epoch_id(redis_conn: aioredis, state_contract_obj, rpc_helper, current_epochId, time_in_seconds):
    source_chain_epoch_size = await get_source_chain_epoch_size(redis_conn, state_contract_obj, rpc_helper)
    source_chain_block_time = await get_source_chain_block_time(redis_conn, state_contract_obj, rpc_helper)

    # calculate tail epochId
    tail_epoch_id = current_epochId - int(time_in_seconds / (source_chain_epoch_size * source_chain_block_time))

    if tail_epoch_id < 1:
        tail_epoch_id = 1

    return tail_epoch_id


async def get_project_epoch_snapshot_bulk(
        redis_conn: aioredis,
        state_contract_obj,
        rpc_helper,
        epochIds: List,
        projectId,
):

    # fetch data for all epochIds using get_project_epoch_snapshot in parallel
    tasks = [
        get_project_epoch_snapshot(
            redis_conn, state_contract_obj, rpc_helper, epochId, projectId,
        ) for epochId in epochIds
    ]

    epoch_snapshots = await asyncio.gather(*tasks)

    return epoch_snapshots
