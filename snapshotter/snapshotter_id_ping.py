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
    try:
        aioredis_pool = RedisPoolCache(pool_size=1000)
        await aioredis_pool.populate()
        redis_conn = aioredis_pool._aioredis_pool

        anchor_rpc = RpcHelper(settings.anchor_chain_rpc)
        await anchor_rpc.init(redis_conn=redis_conn)
        protocol_abi = read_json_file(settings.protocol_state.abi)
        protocol_state_contract = anchor_rpc.get_current_node()['web3_client'].eth.contract(
            address=Web3.toChecksumAddress(
                settings.protocol_state.address,
            ),
            abi=protocol_abi,
        )

        snapshotter_address = to_checksum_address(settings.instance_id)

        snapshotters_arr_query = await anchor_rpc.web3_call(
            [
                protocol_state_contract.functions.allSnapshotters(snapshotter_address),
                protocol_state_contract.functions.slotSnapshotterMapping(settings.slot_id),
            ],
            redis_conn,
        )

        snapshotting_allowed = snapshotters_arr_query[0]
        slot_id_address = snapshotters_arr_query[1]

        if not snapshotting_allowed:
            print('SIGNER_ACCOUNT_ADDRESS has not been assigned as a snapshotter. Exiting...')
            await redis_conn.set(
                active_status_key,
                int(False),
            )
            sys.exit(1)
        if to_checksum_address(slot_id_address) != to_checksum_address(settings.instance_id):
            print('SIGNER_ACCOUNT_ADDRESS is not the one configured in SLOT_ID. Exiting...')
            await redis_conn.set(
                active_status_key,
                int(False),
            )
            sys.exit(1)

        print('Snapshotting allowed...')
        await redis_conn.set(
            active_status_key,
            int(True),
        )
        sys.exit(0)
    except Exception as e:
        print(f'Error when checking snapshotter identity: {e}. Exiting...')
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())
