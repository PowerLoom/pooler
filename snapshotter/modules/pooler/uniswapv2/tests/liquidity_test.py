import asyncio
import json

import httpx
from redis import asyncio as aioredis

from ..utils.core import get_pair_reserves
from snapshotter.utils.redis.rate_limiter import load_rate_limiter_scripts
from snapshotter.utils.redis.redis_conn import provide_async_redis_conn_insta


@provide_async_redis_conn_insta
async def fetch_liquidityUSD_rpc(
    pair_address,
    block_num,
    redis_conn: aioredis.Redis = None,
):
    rate_limiting_lua_scripts = await load_rate_limiter_scripts(redis_conn)
    data = await get_pair_reserves(
        loop,
        rate_limiting_lua_scripts,
        pair_address,
        block_num,
        block_num,
        redis_conn=redis_conn,
    )
    block_pair_total_reserves = data.get(block_num)
    return (
        block_pair_total_reserves['token0USD'] +
        block_pair_total_reserves['token1USD']
    )


def fetch_liquidityUSD_graph(pair_address, block_num):
    uniswap_url = 'https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2'
    uniswap_payload = (
        '{"query":"{\\n pair(id: \\"' +
        str(pair_address) +
        '\\",block:{number:' +
        str(
            block_num,
        ) +
        '}) {\\n reserveUSD \\n token0 { \\n     symbol \\n } \\n token1 {'
        ' \\n      symbol \\n    }\\n  } \\n }" }'
    )
    print(uniswap_payload)
    headers = {'Content-Type': 'application/plain'}
    response = httpx.post(
        url=uniswap_url,
        headers=headers,
        data=uniswap_payload,
        timeout=30,
    )
    if response.status_code == 200:
        data = json.loads(response.text)
        print('Response', data)
        data = data['data']
        return float(data['pair']['reserveUSD'])
    else:
        print('Error fetching data from uniswap THE GRAPH %s', response)
        return 0


async def compare_liquidity():
    total_liquidity_usd_graph = 0
    total_liquidity_usd_rpc = 0
    block_num = 16046250

    contracts = list()
    contracts.append('0xae461ca67b15dc8dc81ce7615e0320da1a9ab8d5')
    for contract in contracts:
        liquidity_usd_graph = fetch_liquidityUSD_graph(contract, block_num)
        liquidity_usd_rpc = await fetch_liquidityUSD_rpc(contract, block_num)
        print(
            f'Contract {contract}, liquidityUSD_graph is'
            f' {liquidity_usd_graph} , liquidityUSD_rpc {liquidity_usd_rpc},'
            ' liquidityUSD difference'
            f' {(liquidity_usd_rpc - liquidity_usd_graph)}',
        )
        total_liquidity_usd_graph += liquidity_usd_graph
        total_liquidity_usd_rpc += liquidity_usd_rpc

    print(
        f'{len(contracts)} contracts compared, liquidityUSD_rpc_total is'
        f' {total_liquidity_usd_rpc}, liquidityUSD_graph_total is'
        f' {total_liquidity_usd_graph}',
    )


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(compare_liquidity())
