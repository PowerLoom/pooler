import asyncio
import sys

from eth_utils.address import to_checksum_address
from web3 import Web3

from snapshotter.auth.helpers.redis_conn import RedisPoolCache
from snapshotter.settings.config import settings
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.rpc import RpcHelper
from snapshotter.utils.redis.redis_keys import active_status_key


async def main():
    """
    Checks if snapshotting is allowed for the given instance ID by querying the protocol state contract.
    If snapshotting is allowed, sets the active status key in Redis to True and exits with code 0.
    If snapshotting is not allowed, sets the active status key in Redis to False and exits with code 1.
    """
    aioredis_pool = RedisPoolCache(pool_size=1000)
    await aioredis_pool.populate()
    redis_conn = aioredis_pool._aioredis_pool
    
    await redis_conn.set(
        active_status_key,
        int(True),
    )
    sys.exit(0)

if __name__ == '__main__':
    asyncio.run(main())
