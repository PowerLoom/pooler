import asyncio
import sys

from eth_utils.address import to_checksum_address
from web3 import Web3

from snapshotter.auth.helpers.redis_conn import RedisPoolCache
from snapshotter.settings.config import settings
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.redis.redis_keys import active_status_key
from snapshotter.utils.rpc import RpcHelper


async def main():
    """
    Checks if snapshotting is allowed for the given instance ID by querying the protocol state contract.
    If snapshotting is allowed, sets the active status key in Redis to True and exits with code 0.
    If snapshotting is not allowed, sets the active status key in Redis to False and exits with code 1.
    """
    aioredis_pool = RedisPoolCache(pool_size=1000)
    await aioredis_pool.populate()
    redis_conn = aioredis_pool._aioredis_pool
    anchor_rpc = RpcHelper(settings.anchor_chain_rpc)
    print('Anchor rpc settings: ', settings.anchor_chain_rpc)
    await anchor_rpc.init(redis_conn=redis_conn)
    protocol_abi = read_json_file(settings.protocol_state.abi)
    print('abi file ', settings.protocol_state.abi)
    print('Contract address: ', settings.protocol_state.address)
    snapshotters_arr_query = await anchor_rpc.web3_call(
        tasks=[('allSnapshotters', Web3.to_checksum_address(settings.instance_id))],  # tuple of method name and args
        contract_addr=settings.protocol_state.address,
        abi=protocol_abi
    )
    allowed_snapshotters = snapshotters_arr_query[0]
    if allowed_snapshotters is True or allowed_snapshotters:
        print('Snapshotting allowed...')
        await redis_conn.set(
            active_status_key,
            int(True),
        )
        sys.exit(0)
    else:
        print('Snapshotting not allowed...')
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
