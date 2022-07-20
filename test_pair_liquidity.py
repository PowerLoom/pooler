from time import time
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
    current_time = time()
    uniswap_url = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2"
    uniswap_payload = "{\"query\":\"{\\n pair(id: \\\"" + str(pair_address) + "\\\") {\\n reserveUSD \\n token0 { \\n     symbol \\n } \\n token1 { \\n      symbol \\n    }\\n  } \\n }\" }"
    print(uniswap_payload)
    headers = {'Content-Type': 'application/plain'}
    response = requests.request("POST", uniswap_url, headers=headers, data=uniswap_payload)
    if response.status_code == 200:
        data = json.loads(response.text)
        print("Response",data)
        data = data["data"]
        return float(data['pair']['reserveUSD'])
    else:
        print(f"Error fetching data from uniswap THE GRAPH %s",response)
        return 0

contracts = load_contracts()
total_liquidityUSD_graph = 0
total_liquidityUSD_rpc = 0

#contracts = list()
#contracts.append("0xae461ca67b15dc8dc81ce7615e0320da1a9ab8d5")
for contract in contracts:
    liquidityUSD_graph = fetch_liquidityUSD_graph(contract)
    liquidityUSD_rpc = fetch_liquidityUSD_rpc(contract)
    print(f"Contract {contract}, liquidityUSD_graph is {liquidityUSD_graph} , liquidityUSD_rpc {liquidityUSD_rpc}, liquidityUSD difference {(liquidityUSD_rpc - liquidityUSD_graph)}")
    total_liquidityUSD_graph += liquidityUSD_graph
    total_liquidityUSD_rpc += liquidityUSD_rpc

print(f"{len(contracts)} contracts compared, liquidityUSD_rpc_total is {total_liquidityUSD_rpc}, liquidityUSD_graph_total is {total_liquidityUSD_graph}")