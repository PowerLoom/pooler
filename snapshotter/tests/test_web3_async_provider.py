import asyncio
import json

from eth_utils.address import to_checksum_address
from web3 import HTTPProvider
from web3 import Web3

from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import logger
from snapshotter.utils.rpc import RpcHelper


async def test_web3_async_call():
    with open('snapshotter/tests/static/abi/storage_contract.json') as f:
        contract_abi = json.load(f)
    rpc_helper = RpcHelper(settings.anchor_chain_rpc)
    await rpc_helper.init()
    sync_w3_client = Web3(HTTPProvider(settings.anchor_chain_rpc.full_nodes[0].url))
    contract_obj = sync_w3_client.eth.contract(
        address=to_checksum_address('0x31b554545279DBB438FC66c55A449263a6b56dB5'),
        abi=contract_abi,
    )
    # print(await contract.functions.retrieve().call())
    tasks = [
        contract_obj.functions.retrieve(),
    ]
    result = await rpc_helper.web3_call(tasks)
    logger.debug('Retrieve: {}', result)


if __name__ == '__main__':
    try:
        asyncio.get_event_loop().run_until_complete(test_web3_async_call())
    except Exception as e:
        logger.opt(exception=True).error('exception: {}', e)
