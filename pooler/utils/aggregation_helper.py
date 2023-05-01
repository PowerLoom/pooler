from redis import asyncio as aioredis

from pooler.utils.default_logger import logger
from pooler.utils.ipfs_async import async_ipfs_client as ipfs_client
from pooler.utils.redis.redis_keys import get_cid_data
from pooler.utils.redis.redis_keys import get_project_finalized_data_zset
from pooler.utils.redis.redis_keys import get_project_first_epoch_hmap

logger = logger.bind(module='data_helper')


async def get_project_finalized_cid(redis_conn: aioredis, state_contract_obj, rpc_helper, epochId, projectId):

    project_first_epoch = await get_project_first_epoch(redis_conn, state_contract_obj, rpc_helper, projectId)
    logger.info('First Project Epoch {} {}', epochId, project_first_epoch)
    if epochId < project_first_epoch:
        return None

    # if data is present in finalzied data zset, return it
    [cid] = await redis_conn.zrangebyscore(
        get_project_finalized_data_zset(projectId),
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
            get_project_finalized_data_zset(projectId),
            epochId,
            cid,
        )
        return cid
    else:
        return None


async def get_project_first_epoch(redis_conn: aioredis, state_contract_obj, rpc_helper, projectId):
    first_epoch_data = await redis_conn.hget(
        get_project_first_epoch_hmap(),
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
            get_project_first_epoch_hmap(),
            projectId,
            first_epoch,
        )

        return first_epoch


async def get_submission_data(redis_conn: aioredis, cid):
    # TODO: Using redis for now, find better way to cache this data
    logger.info('CID {}, fetching data from IPFS', cid)
    submission_data = await redis_conn.get(
        get_cid_data(cid),
    )
    if submission_data:
        logger.info('CID {}, found data in redis', cid)
        return submission_data
    else:
        # Fetch from IPFS
        logger.info('CID {}, fetching data from IPFS', cid)
        submission_data = await ipfs_client.async_cat(cid)
        await redis_conn.set(
            get_cid_data(cid),
            submission_data,
        )

        return submission_data


async def get_project_epoch_snapshot(redis_conn: aioredis, state_contract_obj, rpc_helper, epochId, projectId):
    cid = await get_project_finalized_cid(redis_conn, state_contract_obj, rpc_helper, epochId, projectId)
    if cid:
        return await get_submission_data(redis_conn, cid)
    else:
        return None
