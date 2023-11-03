

import json
import web3
from web3 import Web3
from web3.contract import Contract
from pooler import settings
from pooler.modules.uniswapv3.utils.constants import UNISWAP_EVENTS_ABI

from pooler.utils.rpc import RpcHelper

import asyncio
import json
from aiohttp import ClientTimeout, ClientSession, TCPConnector
from eth_utils import to_checksum_address
from web3 import Web3, AsyncHTTPProvider, HTTPProvider
from web3.eth import AsyncEth
from pooler.utils.default_logger import logger
from pooler.settings.config import settings
from pooler.utils.redis.redis_conn import RedisPoolCache
from pooler.utils.rpc import RpcHelper
mint_topic = Web3.keccak(
        text="Mint(address,address,int24,int24,uint128,uint256,uint256)",
    ).hex()

burn_topic = Web3.keccak(
        text="Burn(address,int24,int24,uint128,uint256,uint256)",
    ).hex()

print(mint_topic)   
print(burn_topic)
block = 18486307

async def test_web3_async_call():

    # aioredis_pool = RedisPoolCache()
    
    # await aioredis_pool.populate()
    # writer_redis_pool = aioredis_pool._aioredis_pool
    
    rpc_helper = RpcHelper(settings.anchor_chain_rpc)
    # await rpc_helper.init(writer_redis_pool)
    address = '0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640'

    # print(await contract.functions.retrieve().call())
    block = 18486307
    result = await rpc_helper.get_events_logs(address, from_block=block, to_block=block + 10, topics=[mint_topic], event_abi=UNISWAP_EVENTS_ABI.get("Mint"))
    print(result)
    logger.debug("Retrieve: {}", result)


if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(test_web3_async_call())
    except Exception as e:
        logger.opt(exception=True).error("exception: {}", e)











# events = w3.eth.get_logs({
#     "fromBlock": block,
#     "toBlock": block + 10,
#     "address": [address],
#     "topics": [[mint_topic]]
# })
# print(events)
# # print(events[0])
# block_dict = {}
# [block_dict.setdefault(event['blockNumber'], []).append(event) for event in events]
# print(block_dict)
# '0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c'