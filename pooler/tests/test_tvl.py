import os
from web3 import Web3
import asyncio
import sys

from pooler.modules.uniswapv3.utils.constants import erc20_abi
from pooler.modules.uniswapv3.total_value_locked import _load_abi, calculate_reserves
from pooler.modules.uniswapv3.utils.helpers import get_pair_metadata
from pooler.settings.config import settings
from pooler.utils.redis.redis_conn import RedisPoolCache
from pooler.utils.rpc import RpcHelper


async def test_calculate_reserves():
    # Mock your parameters
    pair_address = Web3.to_checksum_address(
        "0x7858E59e0C01EA06Df3aF3D20aC7B0003275D4Bf"
    )
    from_block = 18746454
    rpc_helper = RpcHelper()
    aioredis_pool = RedisPoolCache()

    await aioredis_pool.populate()
    redis_conn = aioredis_pool._aioredis_pool
    pair_per_token_metadata = await get_pair_metadata(
        pair_address=pair_address, redis_conn=redis_conn, rpc_helper=rpc_helper
    )  # Replace with your data

    # Call your async function
    reserves = await calculate_reserves(
        pair_address, from_block, pair_per_token_metadata, rpc_helper, redis_conn
    )

    # Check that it returns an array of correct form
    assert isinstance(reserves, list), "Should return a list"
    assert len(reserves) == 2, "Should have two elements"

    # Initialize Web3
    w3 = Web3(Web3.HTTPProvider(settings.rpc.full_nodes[0].url))
    contract = w3.eth.contract(
        address=pair_address,
        abi=_load_abi("pooler/tests/static/abi/UniswapV3Pool.json"),
    )
    token0 = contract.functions.token0().call()
    token1 = contract.functions.token1().call()

    token0_contract = w3.eth.contract(address=token0, abi=erc20_abi)
    token1_contract = w3.eth.contract(address=token1, abi=erc20_abi)
    # Fetch actual reserves from blockchain
    # The function name 'getReserves' and the field names may differ based on the actual ABI
    token0_actual_reserve = token0_contract.functions.balanceOf(pair_address).call()
    token1_actual_reserve = token1_contract.functions.balanceOf(pair_address).call()

    print(reserves)
    print(token0_actual_reserve, token1_actual_reserve)

    # Compare them with returned reserves
    # our calculations should be less than or equal to token balance.
    #  assuming a maximum of 30%? of token balance is unpaid fees
    assert (
        reserves[0] >= token0_actual_reserve * 0.8
    ), "calculated reserve is lower than 90% token balance"
    assert (
        reserves[0] <= token0_actual_reserve
    ), "calculated reserve is higher than token balance"
    assert (
        reserves[1] >= token1_actual_reserve * 0.8
    ), "calculated reserve is lower than 90% token balance"
    assert (
        reserves[1] <= token1_actual_reserve
    ), "calculated reserve is higher than token balance"
    print("PASSED")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(test_calculate_reserves())
