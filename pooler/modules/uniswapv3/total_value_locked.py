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
from pooler.modules.uniswapv3.utils.constants import MAX_TICK, MIN_TICK
from pooler.modules.uniswapv3.redis_keys import uniswap_cached_tick_data_block_height

from pooler.utils.rpc import RpcHelper, get_event_sig_and_abi

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
    sqrt_price = sqrt_price / 2 ** 96
    liquidity_total = 0
    token0_liquidity = 0
    token1_liquidity = 0
    tick_spacing = 1

    if len(ticks) == 0:
        return (0, 0)

    # returned as string from redis cache, returned as int from pair contract's fee()
    int_fee = int(pair_metadata["pair"]["fee"])

    if int_fee == 3000:
        tick_spacing = 60
    elif int_fee == 500:
        tick_spacing = 10
    elif int_fee == 10000:
        tick_spacing = 200
# https://atiselsts.github.io/pdfs/uniswap-v3-liquidity-math.pdf
    for i in range(len(ticks)):
        tick = ticks[i]
        idx = tick["idx"]
        nextIdx = ticks[i + 1]["idx"] \
        if i < len(ticks) - 1 \
        else idx + tick_spacing

        liquidity_net = tick["liquidity_net"]   
        liquidity_total += liquidity_net
        sqrtPriceLow = 1.0001 ** (idx // 2)
        sqrtPriceHigh = 1.0001 ** (nextIdx // 2)
        if sqrt_price <= sqrtPriceLow:
            token0_liquidity += get_token0_in_pool(
                liquidity_total,
                sqrtPriceLow,
                sqrtPriceHigh,
            )
        elif sqrt_price >= sqrtPriceHigh:
            token1_liquidity += get_token1_in_pool(
                liquidity_total,
                sqrtPriceLow,
                sqrtPriceHigh,
            )

        else: 
            token0_liquidity += get_token0_in_pool(
                liquidity_total,
                sqrt_price,
                sqrtPriceHigh
            )
            token1_liquidity += get_token1_in_pool(
                liquidity_total,
                sqrtPriceLow,
                sqrt_price,
            )   
            
    return (token0_liquidity, token1_liquidity)


def get_token0_in_pool(
    liquidity: int,
    
    sqrtPriceLow: int,
    sqrtPriceHigh: int,
) -> int:
    
    return liquidity * (sqrtPriceHigh - sqrtPriceLow) / (sqrtPriceLow * sqrtPriceHigh) // 1


def get_token1_in_pool(
    liquidity: int,
    
    sqrtPriceLow: int,
    sqrtPriceHigh: int,
) -> int:
    
    return liquidity * (sqrtPriceHigh - sqrtPriceLow) // 1


async def get_events(
    pair_address: str,
    rpc: RpcHelper,
    from_block,
    to_block,

    redis_con,
):

    event_sig, event_abi = get_event_sig_and_abi(
        {
            "Mint": UNISWAP_TRADE_EVENT_SIGS['Mint'], 
            "Burn": UNISWAP_TRADE_EVENT_SIGS['Burn']
        },
        UNISWAP_EVENTS_ABI,
    )
    
    
    events = await rpc.get_events_logs(
        contract_address=pair_address,
        to_block=to_block,
        from_block=from_block,
        topics=event_sig,
        event_abi=event_abi,
        redis_conn=redis_con,
        )
    
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

    ticks_list, slot0 = await get_tick_info(
        rpc_helper=rpc_helper,
        pair_address=pair_address,
        from_block=from_block,
        redis_conn=redis_conn,
        pair_per_token_metadata=pair_per_token_metadata,

    )

    sqrt_price = slot0[0]
    t0_reserves, t1_reserves = calculate_tvl_from_ticks(
        ticks_list,
        pair_per_token_metadata,
        sqrt_price,
    )

    return [int(t0_reserves), int(t1_reserves)]


async def get_tick_info(
        rpc_helper: RpcHelper,
        pair_address: str,  
        from_block,
        redis_conn,
        pair_per_token_metadata,
    
):
        # get token price function takes care of its own rate limit
    overrides = {
        override_address: {"code": univ3_helper_bytecode},
    }

    cached_tick_dict = await redis_conn.zrangebyscore(
        name=uniswap_cached_tick_data_block_height.format(
                Web3.to_checksum_address(pair_address),
        ),
        min=int(from_block),
        max=int(from_block),
    )

    if cached_tick_dict:
        tick_dict = json.loads(cached_tick_dict[0])
        return tick_dict["ticks_list"], tick_dict["slot0"]

    current_node = rpc_helper.get_current_node()
    pair_contract = current_node['web3_client'].eth.contract(address=pair_address, abi=pair_contract_abi)
    int_fee = int(pair_per_token_metadata["pair"]["fee"])

    # batch rpc calls for tick data to prevent oog errors
    if int_fee == 100:
        step = (MAX_TICK - MIN_TICK) // 4
        tick_tasks = []

        for i in range(MIN_TICK, MAX_TICK, step):
            upper = i + step

            # account for rounding
            if upper > MAX_TICK or (upper + step) > MAX_TICK:
                tick_tasks.append(helper_contract.functions.getTicks(pair_address, i, MAX_TICK))

            # upper - 1 because getTicks() is inclusive for start and end ticks
            else:
                tick_tasks.append(helper_contract.functions.getTicks(pair_address, i, upper - 1))

    elif int_fee == 500:
        tick_tasks = [
            helper_contract.functions.getTicks(pair_address, MIN_TICK, int(-1)),   
            helper_contract.functions.getTicks(pair_address, int(0), MAX_TICK),   
        ]
        
    else:
        tick_tasks = [
            helper_contract.functions.getTicks(pair_address, MIN_TICK, MAX_TICK) 
        ]

    # for i in range(MIN_TICK, MAX_TICK, 221818):
    #     next_tick = MAX_TICK if i + 221818 > MAX_TICK else i + 221818
    #     tick_tasks.append(
    #         helper_contract.functions.getTicks(pair_address, i, next_tick)
        # )

    slot0_tasks = [
        pair_contract.functions.slot0(),
    ]
    
    # cant batch these tasks due to implementation of web3_call re: state override
    tickDataResponse, slot0Response = await asyncio.gather(
        rpc_helper.web3_call(tick_tasks, redis_conn, overrides=overrides, block=from_block),
        rpc_helper.web3_call(slot0_tasks, redis_conn, block=from_block,),
        )
        
    ticks_list = []
    for ticks in tickDataResponse:
        ticks_list.append(transform_tick_bytes_to_list(ticks))
    
    ticks_list = functools.reduce(lambda x, y: x + y, ticks_list)
    slot0 = slot0Response[0]

    if len(ticks_list) > 0:
        redis_cache_mapping = {
            json.dumps({"blockHeight": from_block, "slot0": slot0, "ticks_list": ticks_list,}): int(from_block)
        }

        await redis_conn.zadd(
            name=uniswap_cached_tick_data_block_height.format(
                Web3.to_checksum_address(pair_address),
            ),
            mapping=redis_cache_mapping,  # timestamp so zset do not ignore same height on multiple heights
        )

    return ticks_list, slot0
