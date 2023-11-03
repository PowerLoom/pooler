import asyncio
import functools
import json
from typing import Union

from eth_abi import abi
from eth_typing import Address
from eth_typing.evm import Address
from eth_typing.evm import ChecksumAddress
from web3 import Web3
from web3.contract import Contract

from pooler.modules.uniswapv3.utils.constants import helper_contract
from pooler.modules.uniswapv3.utils.constants import UNISWAP_TRADE_EVENT_SIGS
from pooler.modules.uniswapv3.utils.constants import pair_contract_abi
from pooler.modules.uniswapv3.utils.constants import override_address
from pooler.modules.uniswapv3.utils.constants import univ3_helper_bytecode
from pooler.modules.uniswapv3.utils.constants import UNISWAP_EVENTS_ABI

from pooler.utils.rpc import RpcHelper

AddressLike = Union[Address, ChecksumAddress]


def transform_tick_bytes_to_list(tickData: bytes):
    # eth_abi decode tickdata as a bytes[]
    bytes_decoded_arr = abi.decode(
        ("bytes[]", "(int128,int24)"), tickData
    )
    ticks = [
        {
            "liquidity_net": int.from_bytes(i[:-3], "big", signed=True),
            "idx": int.from_bytes(i[-3:], "big", signed=True),
        }
        for i in bytes_decoded_arr[0]
    ]

    return ticks


def calculate_tvl_from_ticks(ticks, pair_metadata, sqrt_price):
    sqrt_price = sqrt_price / (1 << 96)
    liquidity_total = 0
    token0_liquidity = 0
    token1_liquidity = 0
    tick_spacing = 10

    if len(ticks) == 0:
        return (0, 0)

    if pair_metadata["pair"]["fee"] == 3000:
        tick_spacing = 60
    elif pair_metadata["pair"]["fee"] == 10000:
        tick_spacing = 200

    for tick in ticks:
        liquidity_net = tick["liquidity_net"]
        idx = tick["idx"]
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
    pair_address: str,
    rpc: RpcHelper,
    from_block,
    to_block,

    redis_con,
):
    # TODO abstract this out to a existing function
    mint_topic = Web3.keccak(
        text=UNISWAP_TRADE_EVENT_SIGS.get("Mint"),  
    ).hex()
    burn_topic = Web3.keccak(
        text=UNISWAP_TRADE_EVENT_SIGS.get("Burn"),
    ).hex()

    topics = [[mint_topic], [burn_topic]]


    
    event_abi = dict()
    
    event_abi[mint_topic] = UNISWAP_EVENTS_ABI.get("Mint")
    event_abi[burn_topic] = UNISWAP_EVENTS_ABI.get("Burn")

    
    try: 
        mint_events, burn_events =  await asyncio.gather(
            rpc.get_events_logs(
            contract_address=pair_address,
            to_block=to_block,
            from_block=from_block,
            topics=topics[0],
            event_abi=event_abi,
            redis_conn=redis_con,
            ),
            rpc.get_events_logs(
                contract_address=pair_address,
                to_block=to_block,
                from_block=from_block,
                topics=topics[1],
                event_abi=event_abi,
                redis_conn=redis_con,
                )
            )
    except Exception as e:
        # bubble
        raise e
    
    events = mint_events + burn_events
    
    return events


@functools.lru_cache()
def _load_contract(w3: Web3, abi_name: str, address: AddressLike) -> Contract:
    address = Web3.to_checksum_address(address)
    return w3.eth.contract(address=address, abi=_load_abi(abi_name))


def _load_abi(path: str) -> str:
    with open(path) as f:
        abi: str = json.load(f)
    return abi


async def calculate_reserves(
    pair_address: str,
    from_block,
    pair_per_token_metadata,
    rpc_helper: RpcHelper,
    redis_conn,
):

    # get token price function takes care of its own rate limit
    overrides = {
        override_address: {"code": univ3_helper_bytecode},
    }
    current_node = rpc_helper.get_current_node()
    pair_contract = current_node['web3_client'].eth.contract(address=pair_address, abi=pair_contract_abi)
    tick_tasks = [helper_contract.functions.getTicks(pair_address)]
    slot0_tasks = [
        pair_contract.functions.slot0(),
    ]
    
    # cant batch these tasks due to implementation of web3_call re: state override
    tickDataResponse, slot0Response = await asyncio.gather(
        rpc_helper.web3_call(tick_tasks, redis_conn, overrides=overrides, block=from_block),
        rpc_helper.web3_call(slot0_tasks, redis_conn, block=from_block,),
        )
        

    ticks_list = transform_tick_bytes_to_list(tickDataResponse[0])
    slot0 = slot0Response[0]

    sqrt_price = slot0[0]
    t0_reserves, t1_reserves = calculate_tvl_from_ticks(
        ticks_list,
        pair_per_token_metadata,
        sqrt_price,
    )

    return [t0_reserves, t1_reserves]
