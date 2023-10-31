import functools
import json

from typing import Union
from eth_abi import abi

from pooler.modules.uniswapv3.utils.constants \
import pair_contract_abi, current_node, max_gas_static_call, univ3_helper_bytecode, helper_contract_abi, \
override_address

from eth_typing import Address
from eth_typing.evm import Address
from eth_typing.evm import ChecksumAddress
from redis import asyncio as aioredis

from web3 import Web3
from web3.contract import Contract
from pooler import settings

from pooler.modules.uniswapv3.utils.helpers import get_pair_metadata
from pooler.utils.file_utils import read_json_file
from pooler.utils.rpc import get_contract_abi_dict
from pooler.utils.rpc import RpcHelper

AddressLike = Union[Address, ChecksumAddress]

def transform_tick_bytes_to_list(tickData):
    # eth_abi decode tickdata as a bytes[] 
    bytes_decoded_arr = abi.decode(("bytes[]", "(int128,int24)"), tickData, strict=False)
    ticks = [
        {
            "liquidity_net": int.from_bytes(i[:-3], "big", signed=True),
            "idx": int.from_bytes(i[-3:], "big", signed=True),
        }
        for i in bytes_decoded_arr[0]
    ]
    
    # while counter < len(tickData):
    #     bytes = tickData[counter : counter + 64]
    #     if bytes[-2] != "13":
    #         counter += 64
    #     else:
    #         tick = {
    #             "liquidity_net": Web3.to_int(
    #                 "0x" + tickData[counter + 64 : counter + 96]
    #             ),
    #             "index": "0x" + tickData[counter + 96 : counter + 102],
    #         }

    #         ticks.append(tick)
    #         counter += 128

    return ticks


def calculate_tvl_from_ticks(ticks, pair_metadata, sqrt_price):
    sqrt_price = sqrt_price / (1 << 96)
    liquidity_total = 0
    token0_liquidity = 0
    token1_liquidity = 0
    tick_spacing = 10

    if len(ticks) == 0:
        return (0, 0)
    
    if pair_metadata['pair']['fee'] == 3000:
        tick_spacing = 60
    elif pair_metadata['pair']['fee'] == 10000:
        tick_spacing = 200

    for tick in ticks:
        liquidity_net = tick['liquidity_net']
        idx = tick['idx']
        liquidity_total += liquidity_net
        sqrtPriceLow = 1.0001 ** (idx // 2)
        sqrtPriceHigh = 1.0001 ** ((idx + tick_spacing) // 2)
        token0_liquidity += get_token0_in_pool(
            liquidity_total,
            sqrt_price,
            sqrtPriceLow,
            sqrtPriceHigh,
        )
        token1_liquidity += get_token1_in_pool(
            liquidity_total,
            sqrt_price,
            sqrtPriceLow,
            sqrtPriceHigh,
        )


    return (token0_liquidity, token1_liquidity)


def get_token0_in_pool(
    liquidity: int,
    sqrtPrice: int,
    sqrtPriceLow: int,
    sqrtPriceHigh: int,
) -> int:
    sqrtPrice = max(min(sqrtPrice, sqrtPriceHigh), sqrtPriceLow)
    return liquidity * (sqrtPriceHigh - sqrtPrice) // (sqrtPrice * sqrtPriceHigh)


def get_token1_in_pool(
    liquidity: int,
    sqrtPrice: int,
    sqrtPriceLow: int,
    sqrtPriceHigh: int,
) -> int:
    sqrtPrice = max(min(sqrtPrice, sqrtPriceHigh), sqrtPriceLow)
    return liquidity * (sqrtPrice - sqrtPriceLow)


async def get_events(
    pair_address: str, rpc: RpcHelper, from_block, to_block, redis_con
):
    contract = _load_contract(pair_address, "/static/abis/UniswapV3Pool", pair_address)
    mint_topic = Web3.keccak(
        text="Mint(address,address,uint256,uint256,uint128,int24)"
    ).hex()
    burn_topic = Web3.keccak(
        text="Burn(address,address,uint256,uint256,uint128,int24)"
    ).hex()
    topics = [[mint_topic], [burn_topic]]

    event_abi = dict()
    event_abi[mint_topic] = contract.events.Mint().abi
    event_abi[burn_topic] = contract.events.Burn().abi

    return await rpc.get_events_logs(
        contract_address=pair_address,
        to_block=to_block,
        from_block=from_block,
        topics=topics,
        event_abi=event_abi,
        redis_con=redis_con,
    )


@functools.lru_cache()
def _load_contract(w3: Web3, abi_name: str, address: AddressLike) -> Contract:
    address = Web3.to_checksum_address(address)
    return w3.eth.contract(address=address, abi=_load_abi(abi_name))


def _load_abi(path: str) -> str:
    with open(path) as f:
        abi: str = json.load(f)
    return abi


async def calculate_reserves(
    pair_address,
    from_block,
    pair_per_token_metadata,
    rpc_helper: RpcHelper,
    redis_conn,
):
    w3_client = rpc_helper.get_current_node()
    w3 = w3_client['web3_client_async'] if w3_client['web3_client_async'] else w3_client['web3_client']

    # get token price function takes care of its own rate limit
    overrides = {
        override_address: {"code": univ3_helper_bytecode}
    }

    override_contract = w3.eth.contract(abi=helper_contract_abi, address=override_address)

    # create a web3 transaction object for a static state override call to the getTicks function of the helper
    txn_params = override_contract.functions.getTicks(Web3.to_checksum_address(pair_address)).build_transaction(
        {   
            "gas": max_gas_static_call
        },
    )

    # get tick data 
    # build a web3 eth_call with txn_params and use overrides for state override calls
    response = w3.eth.call(txn_params, block_identifier=from_block, state_override=overrides)
    
    # to_checksum_address the helper address, and make an eth_call to get the tick data
    # the call functions in rpc_helper.py do not correctly decode the tick byte data

    ticks_list = transform_tick_bytes_to_list(response)
    pair_contract_obj: Contract = w3.eth.contract(
                address=Web3.to_checksum_address(pair_address),
                abi=pair_contract_abi,
            )
    
    tasks = [
        pair_contract_obj.functions.slot0()
    ]

    slot0 = await rpc_helper.web3_call(tasks, redis_conn)
    sqrt_price = slot0[0][0]
    t0_reserves, t1_reserves = calculate_tvl_from_ticks(
        ticks_list,
        pair_per_token_metadata,
        sqrt_price,
    )

    return [t0_reserves, t1_reserves]
