from web3 import Web3
from dynaconf import settings
import asyncio
from functools import partial
import json
from uniswap_functions import get_liquidity_of_each_token_reserve_async
import os
import requests

def load_contracts():
    contracts = list()
    if os.path.exists('static/cached_pair_addresses.json'):
        with open('static/cached_pair_addresses.json', 'r') as fp:
            # the file contains an array of pair contract addresses
            contracts = json.load(fp)
            return contracts

def fetch_liquidityUSD_rpc(pair_address):
    loop = asyncio.get_event_loop()
    rate_limit_lua_script_shas = dict()
    data = loop.run_until_complete(
        get_liquidity_of_each_token_reserve_async(loop, rate_limit_lua_script_shas, pair_address )
    )
    return data['token0USD']+data['token1USD']


def fetch_liquidityUSD_graph(pair_address):
    uniswap_url = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2"
    uniswap_payload = "{\"query\":\"{\\n  mints(orderBy: timestamp, orderDirection: desc, where:{\\n    pair: \\\""+str(pair_address)+"\\\",\\n    timestamp_lt: "+ str(current_time)+ "\\n  }) {\\n    id,\\n    timestamp,\\n    amountUSD,\\n    logIndex,\\n    feeTo,\\n    feeLiquidity,\\n    amount0,\\n    amount1\\n  },\\n  swaps(orderBy: timestamp, orderDirection: desc, where:{\\n    pair: \\\""+str(pair_contract)+"\\\",\\n    timestamp_lt: "+ str(current_time)+ "\\n  }) {\\n    id,\\n    timestamp,\\n    amountUSD,\\n    logIndex,\\n    amount0In,\\n    amount0Out,\\n    amount1Out,\\n    amount1In\\n  },\\n  burns(orderBy: timestamp, orderDirection: desc, where:{\\n    pair: \\\""+str(pair_contract)+"\\\",\\n    timestamp_lt: "+ str(current_time)+ "\\n  }) {\\n    id,\\n    timestamp,\\n    amountUSD,\\n    logIndex,\\n    amount0,\\n    amount1\\n  }\\n}\\n\",\"variables\":null}"
    headers = {'Content-Type': 'text/plain'}
    response = requests.request("POST", uniswap_url, headers=headers, data=uniswap_payload)
    if response.status_code == 200:
        timestamp_24h = current_time - 60 * 60 * 24
        total_trades_in_usd = 0
        data = json.loads(response.text)
        data = data["data"]
        for each_event in data:
            for obj in data[each_event]:
                if int(obj['timestamp']) >= int(timestamp_24h):
                    debug_trade_logs["uniswap"][each_event].append(obj)
                    total_trades_in_usd += int(float(obj['amountUSD']))
        trade_volume_data["uniswap_24h_trade_volume"] = int(total_trades_in_usd)
    else:
        print(f"Error fetching data from uniswap THE GRAPH")
        trade_volume_data["uniswap_24h_trade_volume"] = None



liq = fetch_liquidityUSD('0x70258aa9830c2c84d855df1d61e12c256f6448b4')
