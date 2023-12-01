import asyncio
from functools import reduce
import json
import math
import os
import time
import decimal
from decimal import *
from eth_abi import abi
import eth_abi
from eth_utils import to_checksum_address
from web3 import AsyncHTTPProvider
from web3 import HTTPProvider
from web3 import Web3
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport

from pooler.modules.uniswapv3.total_value_locked import get_token0_in_pool, get_token1_in_pool
from pooler.modules.uniswapv3.utils.constants import UNISWAP_TRADE_EVENT_SIGS
getcontext().prec = 100 
bytecode = "0x6080604052600436101561001257600080fd5b60003560e01c639c4c90fc1461002757600080fd5b346106dd5760607ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc3601126106dd5760043573ffffffffffffffffffffffffffffffffffffffff811681036106dd5760243560020b602435036106dd5760443560020b604435036106dd577fd0c93a7c00000000000000000000000000000000000000000000000000000000608052602060806004608073ffffffffffffffffffffffffffffffffffffffff85165afa80156106ea57600090610ad2575b60443560020b60243560020b13610a74577ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff2761860243560020b121580610a62575b15610a04577fffffffffffffffffffffffffffffffffffffffffffffffffffffffffff800000602435600290810b60443590910b03908112627fffff909113176102cb57627fffff602435600290810b604435820b03900b6001019081137fffffffffffffffffffffffffffffffffffffffffffffffffffffffffff800000909112176102cb576101c881600160243560020b60443560020b0360020b01610b4c565b60020b907fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe061020f6101f984610bd8565b936102076040519586610b0b565b808552610bd8565b01366020840137600061022482602435610b4c565b60020b60081d60010b9361023a83604435610b4c565b60020b60081d60010b945b858160010b136106f6576040517f5339c2960000000000000000000000000000000000000000000000000000000081528160010b600482015260208160248173ffffffffffffffffffffffffffffffffffffffff87165afa9081156106ea576000916106b3575b50805b6102fa5750617fff8160010b146102cb57600190810b01610245565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052601160045260246000fd5b8060ff6fffffffffffffffffffffffffffffffff8216156106a75750607f5b67ffffffffffffffff83161561069d5760ff7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc081831601116102cb5760ff167fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc0015b63ffffffff8316156106935760ff7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe081831601116102cb5760ff167fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0015b61ffff8316156106895760ff7ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff081831601116102cb5760ff167ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff0015b60ff83161561067f5760ff7ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff881831601116102cb5760ff167ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff8015b600f8316156106755760ff7ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc81831601116102cb5760ff167ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc015b60038316156106695760ff7ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe81831601116102cb577ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe60ff6001921601925b16610611575b600160ff831690811b919091189190600287810b91810b600886901b820b17810b919091029081900b036102cb5760243560020b8660020b60ff831660020b8560081b60020b1760020b0260020b1215806105e9575b6105b2575b50806102af565b9381906105e36105c182610bf0565b9660ff8960020b911660020b8660081b60020b1760020b0260020b9189610c1d565b526105ab565b5060443560020b8660020b60ff831660020b8560081b60020b1760020b0260020b13156105a6565b9060ff7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff81831601116102cb5760ff167fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff0190610550565b9160019060021c61054a565b9160041c916104eb565b9160081c91610490565b9160101c91610435565b9160201c916103d9565b9160401c9161037b565b91508060801c91610319565b90506020813d6020116106e2575b816106ce60209383610b0b565b810103126106dd5751386102ac565b600080fd5b3d91506106c1565b6040513d6000823e3d90fd5b50908361070282610bd8565b926107106040519485610b0b565b82845261071c83610bd8565b60005b7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0820181106109d057505060005b838110610823578460405160208101916020825280518093526040820192602060408260051b8501019201906000945b81861061078a5784840385f35b9091927fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc0858203018252835180519081835260005b82811061080e575050602080837fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0601f85600085809860019a010152011601019501920195019491909161077d565b806020809284010151828287010152016107bf565b61082d8184610c1d565b5160020b90604051917ff30dba9300000000000000000000000000000000000000000000000000000000835260048301526101008260248173ffffffffffffffffffffffffffffffffffffffff87165afa9182156106ea57600092610924575b506108988185610c1d565b516040519260801b602084015260e81b60308301526013825281604081011067ffffffffffffffff6040840111176108f5578160406108f093016040526108df8288610c1d565b526108ea8187610c1d565b50610bf0565b61074d565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052604160045260246000fd5b909150610100813d610100116109c8575b816109436101009383610b0b565b810103126106dd5780516fffffffffffffffffffffffffffffffff8116036106dd5760208101519081600f0b82036106dd5760808101518060060b036106dd5760a081015173ffffffffffffffffffffffffffffffffffffffff8116036106dd5760c081015163ffffffff8116036106dd5760e00151801515036106dd57908661088d565b3d9150610935565b6020816060827fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0948a01015201905061071f565b60646040517f08c379a000000000000000000000000000000000000000000000000000000000815260206004820152601160248201527f7469636b206f7574206f662072616e67650000000000000000000000000000006044820152fd5b50620d89e860443560020b1315610125565b60646040517f08c379a000000000000000000000000000000000000000000000000000000000815260206004820152601160248201527f66726f6d7469636b203e20746f7469636b0000000000000000000000000000006044820152fd5b5060203d602011610b04575b80610aec6020926080610b0b565b126106dd576080518060020b8103156100e557600080fd5b503d610ade565b90601f7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0910116810190811067ffffffffffffffff8211176108f557604052565b60020b9060020b908115610ba9577fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff82147fffffffffffffffffffffffffffffffffffffffffffffffffffffffffff8000008214166102cb570590565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052601260045260246000fd5b67ffffffffffffffff81116108f55760051b60200190565b7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff81146102cb5760010190565b8051821015610c315760209160051b010190565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052603260045260246000fdfea264697066735822122021a0cb19175e38fac75f1f4cead70601985274c34520f27293f6f2f293f91ac064736f6c63430008130033"
MIN_TICK = -887272
MAX_TICK = -MIN_TICK

address = to_checksum_address("0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640")
token0_address = to_checksum_address("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48")
token1_address = to_checksum_address("0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2")

def token1_amount(liquidity: Decimal, sqrtP_a: Decimal, sqrtP_b: Decimal):
    if sqrtP_b > sqrtP_a:
        sqrtP_a, sqrtP_b = sqrtP_b, sqrtP_a
    

    amount = liquidity * (sqrtP_a - sqrtP_b)
    return amount


# this part of the test adds all erc20 txns to and from the contract to get tvl. unrealistic for prod, but good for testing
def univ3_tvl_txns(w3: Web3):

    token0_transfers_to_pair = w3.eth.get_logs({
        "fromBlock": 12376728,
        "toBlock": 12386728,
        "address": token0_address,
        "topics": [
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
            None,
            '0x' + '0' * (24) + address[2:],
        ],
    })
    token0_transfers_from_pair = w3.eth.get_logs({
        "fromBlock": 12376728,
        "toBlock": 12386728,
        "address": token0_address,
        "topics": [
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
            '0x' + '0' * (24) + address[2:],
        ],
    })
    token1_transfers_to_pair = w3.eth.get_logs({
        "fromBlock": 12376728,
        "toBlock": 12386728,
        "address": token1_address,
        "topics": [
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
            None,
            '0x' + '0' * (24) + address[2:], 
        ],
    })
    token1_transfers_from_pair = w3.eth.get_logs({
        "fromBlock": 12376728,
        "toBlock": 12386728,
        "address": token1_address,
        "topics": [
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
            '0x' + '0' * (24) + address[2:],
            None,
        ],
    })
    print('token0 transfers to pair')   
    
    sum_token0_to_pair = 0
    sum_token0_from_pair = 0
    sum_token1_to_pair = 0
    sum_token1_from_pair = 0
    all_transfers = token0_transfers_from_pair + token0_transfers_to_pair + token1_transfers_from_pair + token1_transfers_to_pair
    
    for i in range(len(all_transfers)):
        
        event = all_transfers[i]
    
        from_address = w3.to_checksum_address('0x' + event['topics'][1].hex()[-40:])
        to_address = w3.to_checksum_address('0x' + event['topics'][2].hex()[-40:])
        
        
        wad = int(event['data'].hex(), 16)
        
        if from_address == address and event['address'] == token0_address:
            sum_token0_from_pair += wad
        elif to_address == address and event['address'] == token0_address:
            sum_token0_to_pair += wad
        elif from_address == address and event['address'] == token1_address:
            sum_token1_from_pair += wad
        elif to_address == address and event['address'] == token1_address:
            sum_token1_to_pair += wad
    
    token0_net = sum_token0_to_pair - sum_token0_from_pair
    token1_net = sum_token1_to_pair - sum_token1_from_pair
    print('token0 net')
    print(token0_net)
    print('token1 net')
    print(token1_net)
    # sum swap for token0 and token 1, sub fees
    swap_events = w3.eth.get_logs({
        "fromBlock": 12376728,
        "toBlock": 12386728,
        "address": address,
        "topics": [
            "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67",
        ],
    })

    mint_events = w3.eth.get_logs({
        "fromBlock": 12376728,
        "toBlock": 12386728,
        "address": address,
        "topics": [
            w3.keccak(text=UNISWAP_TRADE_EVENT_SIGS['Mint']).hex(),
        ]
    })
    burn_events = w3.eth.get_logs({
        "fromBlock": 12376728,
        "toBlock": 12386728,
        "address": address,
        "topics": [
            w3.keccak(text=UNISWAP_TRADE_EVENT_SIGS['Burn']).hex(),
        ]
    })

    collect_events = w3.eth.get_logs({  
        "fromBlock": 12376728,
        "toBlock": 12386728,
        "address": address,
        "topics": [
            '0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0'
        ]
        }
        )

        


    token0_liquidity_event = 0
    token1_liquidity_event = 0
    for i in range(len(mint_events)):
        event = mint_events[i]
        data = event['data'].hex()
        token0_liquidity_event += int(data[-128:-64], 16)
        token1_liquidity_event += int(data[-64:], 16)
    

    # for i in range(len(burn_events)):
    #     event = burn_events[i]
    #     data = event['data'].hex()
    #     token0_liquidity_event -= int(data[-128:-64], 16)
    #     token1_liquidity_event -= int(data[-64:], 16)

    
    token0_collected = 0
    token1_collected = 0
    for i in range(len(collect_events)):
        event = collect_events[i]
        data = event['data'].hex()
        token0_liquidity_event -= int(data[-128:-64], 16)
        token1_liquidity_event -= int(data[-64:], 16)

    sum_token0_swap = 0
    sum_token1_swap = 0
    for i in range(len(swap_events)):
        event = swap_events[i]
        data = event['data'].hex()
        token0_swap_amount = abi.decode(("int256",), bytes.fromhex(data[2:66]))[0] 
        token1_swap_amount = abi.decode(("int256",), bytes.fromhex(data[66:130]))[0]
        sum_token0_swap += token0_swap_amount #if token0_swap_amount > 0 else 0
        sum_token1_swap += token1_swap_amount #if token1_swap_amount > 0 else 0


    compute_fees_0 = sum_token0_swap * 0.0005
    compute_fees_1 = sum_token1_swap * 0.0005
    check_0 = sum_token0_swap + token0_liquidity_event 
    check_1 = sum_token1_swap + token1_liquidity_event

    return (token0_net, token1_net)
    # this is to check tvl based on txns from inception to a certain block
    # then compare to tvl based on ticks which we will calculate using both current method and set to 0 method and whatever other method
    # we can think of
    






def get_uniswapv3_ticks_test():
    with open(
        "/Users/matthewrivas/programming/Powerloom/pooler/pooler/tests/static/abi/UniswapV3Pool.json"
    ) as f:
        univ3_abi = json.load(f)
    with open(
        "/Users/matthewrivas/programming/Powerloom/pooler/pooler/tests/static/abi/UniV3Helper.json"
    ) as h:
        helper_abi = json.load(h)

    
    url = ""
    print('blah')
    provider = HTTPProvider(url)
    w3 = Web3(provider)
    # first test how many ticks for 1 call
    v3contract = w3.eth.contract(abi=univ3_abi, address=address)
    override_address = to_checksum_address("0x" + "1" * 40)
    override_contract = w3.eth.contract(abi=helper_abi, address=override_address)

    txn_params = override_contract.functions.getTicks(address, int(MIN_TICK), int(0)).build_transaction(
        {
            "maxFeePerGas": 100000000000,
            "maxPriorityFeePerGas": 13318564621,
            "gas": 100000000000000,
        },
    )
    txn_params_2 = override_contract.functions.getTicks(address, int(0), int(MAX_TICK)).build_transaction(
        {
            "maxFeePerGas": 100000000000,
            "maxPriorityFeePerGas": 13318564621,
            "gas": 100000000000000,
        },
    )

    override_params = {
        override_address: {"code": bytecode},
    }
    all_start = time.time()
    start = time.time()
    b = w3.eth.call(txn_params, hex(12386728), override_params)
    b2 = w3.eth.call(txn_params_2, hex(12386728), override_params)

    end = time.time()

    print(f"time to retreive tick data: {end - start}")
    # print(txn[0:90000])

    # decode
    decoded_bytes_arr = abi.decode(("bytes[]", "(int128,int24)"), b, strict=False)
    decoded_bytes_arr_2 = abi.decode(("bytes[]", "(int128,int24)"), b2, strict=False)
    # print(decoded_bytes_arr)

    start = time.time()
    hex_arr = [
        {
            "idx": w3.to_hex(primitive=i[-3:]),
            "liq": w3.to_hex(primitive=i[:-3]),
        }
        for i in decoded_bytes_arr[0]
    ]
    end = time.time()
    print(f"time to decode arr: {end - start}")

    # padded_bytes_arr = [{
    #     "liquidity_net": i[:-6].zfill(64) if i[3] == "0" else bytes.join('f' *),
    #     "idx": i[-6:].zfill(12)
    # }] 0xffffffffffffffffffff1b47f3384f46
    start = time.time()
    # decoded_ticks_arr = [
    #     {
    #         "liquidity_net": int.from_bytes(i[:-6], "big", signed=True),
    #         "idx": int.from_bytes(i[-6:], "big", signed=True),
    #     }
    #     for i in decoded_bytes_arr[0]
    # ]
    decoded_ticks_arr = []
    for i in decoded_bytes_arr[0]:    
        decoded_ticks_arr.append(
            {
                "liquidity_net": int.from_bytes(i[:-3], "big", signed=True),
                "idx": int.from_bytes(i[-3:], "big", signed=True),
            }
        )
    decoded_ticks_arr_2 = []
    for i in decoded_bytes_arr_2[0]:    
        decoded_ticks_arr_2.append(
            {
                "liquidity_net": int.from_bytes(i[:-3], "big", signed=True),
                "idx": int.from_bytes(i[-3:], "big", signed=True),
            }
        )
    




    # for i in decoded_ticks_arr:
    #     if i['liquidity_net'] == 0:
    #         print(i)
    decoded_ticks_arr = decoded_ticks_arr + decoded_ticks_arr_2
    print('decoded ticks arr len')
    print(len(decoded_ticks_arr))
    sorted_decoded_ticks_arr = sorted([i for i in decoded_ticks_arr], key=lambda x: x["idx"])
    
    end = time.time()
    
    print(f"time to decode props: {end - start}")
    print(f"time to for all operations: {end - all_start}")
    # grab all ticks from theGraph
    transport = AIOHTTPTransport(url="https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3")

    gql_client = Client(
        transport=transport,
        fetch_schema_from_transport=True,
    )
    # query graph for tick data from 0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640
    query = gql(
        """
       query {
        pools(where: {id: "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"}, block: {number: 12386728}) {
            id
            ticks(orderBy: tickIdx, where: {liquidityNet_not: "0"}, first: 1000) {
            liquidityNet
            tickIdx
                }
            }
        }
    """
    )
    query2 = gql(
        """
       query {
        pools(where: {id: "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"}, block: {number: 12386728}) {
            id
            ticks(orderBy: tickIdx, where: {liquidityNet_not: "0"}, first: 1000, skip: 1000) {
            liquidityNet
            tickIdx
                }
            }
        }"""
    )
    diff = []
    gql_response = gql_client.execute(query, variable_values={"address": address})
    gql_response2 = gql_client.execute(query2, variable_values={"address": address})
    gql_ticks = gql_response["pools"][0]['ticks'] + gql_response2["pools"][0]['ticks']
    # print(gql_response)  
    # print(len(gql_response['pools']['ticks']))
    print('sorted')
    # print(sorted_decoded_ticks_arr[0:10])
    print(len(sorted_decoded_ticks_arr))
    print('gql')
    # print(gql_response["pools"][0]['ticks'][0:10]) 
    print(len(gql_ticks))
    assert(len(gql_ticks) == len(sorted_decoded_ticks_arr))
    print("assertion passed")
    gql_tvl = reduce(
        lambda x, y: int(x) + int(y),
        [i['liquidityNet'] for i in gql_ticks],
    )
    rpc_tvl = reduce(
        lambda x, y: int(x) + int(y),
        [i['liquidity_net'] for i in sorted_decoded_ticks_arr],
    )
    print('gql sum of net liquidity: should be 0')
    print(gql_tvl)
    print('rpc sum of net liquidity: should be 0')
    print(rpc_tvl)
    assert(gql_tvl == rpc_tvl & gql_tvl == 0)
    print('assertion passed')

    ticks_arr_start_from_min_sqrtP = [{**i, "liquidity_net": abs(i['liquidity_net'])} for i in sorted_decoded_ticks_arr]
    
    token0amt = 0
    token1amt = 0
    liquidity_total = 0
    slot0 = w3.eth.call(
        {
            "to": address,
            "data": "0x3850c7bd",
        },
        hex(12386728),
        
    )
    
    
    sqrt_price = slot0.hex()[:66]
    sqrt_price = int(sqrt_price, 16) / 2 ** 96
    tick_spacing = 10
    for i in range(len(sorted_decoded_ticks_arr)): 
        tick = sorted_decoded_ticks_arr[i]
        idx = tick["idx"]
        nextIdx = sorted_decoded_ticks_arr[i + 1]["idx"] \
        if i < len(sorted_decoded_ticks_arr) - 1 \
        else idx + tick_spacing

        liquidity_net = tick["liquidity_net"]   
        liquidity_total += liquidity_net
        sqrtPriceLow = 1.0001 ** (idx // 2)
        sqrtPriceHigh = 1.0001 ** (nextIdx // 2)
        if sqrt_price <= sqrtPriceLow:
            token0amt += get_token0_in_pool(
                liquidity_total,
                sqrtPriceLow,
                sqrtPriceHigh,
            )
            print('yo')
        elif sqrt_price >= sqrtPriceHigh:
            token1amt += get_token1_in_pool(
                liquidity_total,
                sqrtPriceLow,
                sqrtPriceHigh,
            )
            print('hi')
        else: 
            token0amt += get_token0_in_pool(
                liquidity_total,
                sqrt_price,
                sqrtPriceHigh
            )
            token1amt += get_token1_in_pool(
                liquidity_total,
                sqrtPriceLow,
                sqrt_price,
            )   
            print('hello')

       

        print()
        # token1amt 
    print('token0 amt')
    print(token0amt)
    token0_tvl, token1_tvl = univ3_tvl_txns(w3=w3)
    # we verify our tvl_check by calling balance of tokens on the contract
    token0_balance = w3.eth.call(
        # wow copilot correctly hashed the function signature for us
        {
            "to": token0_address,
            "data": "0x70a08231000000000000000000000000" + address[2:],
        },
        hex(12386728),
    )   
    token1_balance = w3.eth.call(
        # wow copilot correctly hashed the function signature for us
        {
            "to": token1_address,
            "data": "0x70a08231000000000000000000000000" + address[2:],
        },
        hex(12386728),
    )
    token0_balance = int(token0_balance.hex(), 16)
    token1_balance = int(token1_balance.hex(), 16)

    assert (token0_balance >= token0_tvl and token0_tvl > 0.90 * token0_balance)
    assert (token1_balance >= token1_tvl and token1_tvl > 0.90 * token1_balance)
    print('token balances for check assertion passed')   

    
    assert token1_amount <= token0
    
    # for i in range(len(gql_ticks) - 1):
    #     if int(gql_response["pools"][0]['ticks'][i]['tickIdx']) != int(sorted_decoded_ticks_arr[i]['idx']):
    #         diff.append([gql_response["pools"][0]['ticks'][i], sorted_decoded_ticks_arr[i]])
    # gql_dict = {}
    # for tick in gql_ticks:
    #     gql_dict[tick['tickIdx']] = tick['liquidityNet']

    # rpc_dict = {}
    # for tick in sorted_decoded_ticks_arr:
    #     rpc_dict[tick['idx']] = tick['liquidity_net']
    
    # for tick in sorted_decoded_ticks_arr:
    #     if tick['idx'] not in gql_dict:
    #         print('tick not in gql')
    #         print(tick)
    #         # check if tick is included on chain
    #     if tick['liquidity_net'] != gql_dict[tick['idx']]:
    #         print('liquidity net not equal')
    #         print(tick)
    #         print(gql_dict[tick['idx']])

    # print(decoded_hex_arr)
    # print(len(decoded_hex_arr))
    # decoded_ticks = [
    #     {
    #         'idx': w3.to_int(hexstr='0x' + i[-6:]),
    #         'liquidity_net': w3.to_int(hexstr=i[:-6]),
    #     } for i in decoded_hex_arr
    # ]
    # print('ticks')
    # print(decoded_ticks)


if __name__ == "__main__":
    try:
        # asyncio.get_event_loop().run_until_complete(get_uniswapv3_ticks_test())
        get_uniswapv3_ticks_test()
    except Exception as e:
        print(e)
