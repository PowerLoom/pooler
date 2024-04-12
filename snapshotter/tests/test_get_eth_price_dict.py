import asyncio

from snapshotter.utils.snapshot_utils import get_eth_price_usd
from snapshotter.utils.redis.redis_conn import RedisPoolCache
from snapshotter.utils.redis.redis_keys import source_chain_epoch_size_key
from snapshotter.utils.rpc import RpcHelper
from snapshotter.utils.default_logger import logger

async def test_get_eth_price_dict():
    
    from_block = 19634365
    to_block = from_block + 9
    rpc_helper = RpcHelper()
    
    aioredis_pool = RedisPoolCache()
    await aioredis_pool.populate()
    redis_conn = aioredis_pool._aioredis_pool

    # set key for get_block_details_in_block_range
    await redis_conn.set(
        source_chain_epoch_size_key(),
        to_block - from_block,
    )

    price_dict = await get_eth_price_usd(
        from_block=from_block,
        to_block=to_block,
        rpc_helper=rpc_helper,
        redis_conn=redis_conn,
    )
    
    from pprint import pprint
    pprint(price_dict)

if __name__ == '__main__':
    try:
        asyncio.get_event_loop().run_until_complete(test_get_eth_price_dict())
    except Exception as e:
        print(e)
        logger.opt(exception=True).error('exception: {}', e)
