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
    protocol_abi = read_json_file(settings.protocol_state.abi)
    protocol_state_contract = anchor_rpc.get_current_node()['web3_client'].eth.contract(
        address=Web3.to_checksum_address(
            settings.protocol_state.address,
        ),
        abi=protocol_abi,
    )
    snapshotters_arr_query = await anchor_rpc.web3_call(
        [
            protocol_state_contract.functions.getSnapshotters(),
        ],
        redis_conn,
    )
    allowed_snapshotters = snapshotters_arr_query[0]
    if to_checksum_address(settings.instance_id) in allowed_snapshotters:
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