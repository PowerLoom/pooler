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

    bytecode = "0x608080604052600436101561001357600080fd5b60003560e01c63802036f51461002857600080fd5b346106155760207ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc360112610615576004359073ffffffffffffffffffffffffffffffffffffffff82168203610615577fd0c93a7c00000000000000000000000000000000000000000000000000000000815260208160048173ffffffffffffffffffffffffffffffffffffffff86165afa90811561062257600091610975575b506040517f3850c7bd00000000000000000000000000000000000000000000000000000000815260408160048173ffffffffffffffffffffffffffffffffffffffff87165afa80156106225761092f575b508060020b15610900578060020b621b13d10560020b7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe061017361015d83610a1f565b9261016b60405194856109af565b808452610a1f565b013660208301376000918060020b7ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff276180560020b60081d60010b5b8060010b8260020b620d89e80560020b60081d60010b811361062e57604051907f5339c296000000000000000000000000000000000000000000000000000000008252600482015260208160248173ffffffffffffffffffffffffffffffffffffffff8a165afa908115610622576000916105eb575b50805b61026e575060010b617fff811461023f576001016101ad565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052601160045260246000fd5b8060ff6fffffffffffffffffffffffffffffffff8216156105df5750607f5b67ffffffffffffffff8216156105d55760ff7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc0818316011161023f5760ff167fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc0015b63ffffffff8216156105cb5760ff7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0818316011161023f5760ff167fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0015b61ffff8216156105c15760ff7ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff0818316011161023f5760ff167ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff0015b60ff8216156105b75760ff7ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff8818316011161023f5760ff167ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff8015b600f8216156105ad5760ff7ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc818316011161023f5760ff167ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc015b60038216156105a15760ff7ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe818316011161023f577ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe60ff6001921601915b1661054b575b60ff16906001821b18908360020b9060020b8360081b60020b1760020b028060020b90810361023f57807ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff27618839212158061053e575b610524575b50610226565b61053761053088610a37565b9787610a64565b523861051e565b50620d89e8811315610519565b60ff7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff818316011161023f5760ff167fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff016104c4565b9060019060021c6104be565b9060041c9061045f565b9060081c90610404565b9060101c906103a9565b9060201c9061034d565b9060401c906102ef565b90508160801c9061028d565b90506020813d60201161061a575b81610606602093836109af565b81010312610615575138610223565b600080fd5b3d91506105f9565b6040513d6000823e3d90fd5b50505061063a82610a1f565b9261064860405194856109af565b8284527fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe061067584610a1f565b0160005b8181106108ef57505060005b83811061075b578460405160208101916020825280518093526040820192602060408260051b8501019201906000945b8186106106c25784840385f35b9091927fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc0858203018252835180519081835260005b828110610746575050602080837fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0601f85600085809860019a01015201160101950192019501949190916106b5565b806020809284010151828287010152016106f7565b6107658184610a64565b5160020b90604051917ff30dba9300000000000000000000000000000000000000000000000000000000835260048301526101008260248173ffffffffffffffffffffffffffffffffffffffff87165afa91821561062257600092610857575b506107d08185610a64565b516040519260801b602084015260e81b603083015260138252604082019180831067ffffffffffffffff84111761082857610823926040526108128288610a64565b5261081d8187610a64565b50610a37565b610685565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052604160045260246000fd5b909150610100813d610100116108e7575b8161087661010093836109af565b810103126106155780516fffffffffffffffffffffffffffffffff8116036106155760208101519081600f0b82036106155760808101518060060b03610615576108c260a082016109fe565b5060c081015163ffffffff8116036106155760e00151801515036106155790386107c5565b3d9150610868565b806060602080938901015201610679565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052601260045260246000fd5b6040813d60401161096d575b81610948604093836109af565b810103126106155760208161095f610966936109fe565b50016109f0565b503861011a565b3d915061093b565b90506020813d6020116109a7575b81610990602093836109af565b81010312610615576109a1906109f0565b386100c9565b3d9150610983565b90601f7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0910116810190811067ffffffffffffffff82111761082857604052565b51908160020b820361061557565b519073ffffffffffffffffffffffffffffffffffffffff8216820361061557565b67ffffffffffffffff81116108285760051b60200190565b7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff811461023f5760010190565b8051821015610a785760209160051b010190565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052603260045260246000fdfea2646970667358221220b066db1595cf7acb7b895611dc9837f3bd0731b073eef99e736694005439e20864736f6c63430008130033"
    url = "https://mainnet.infura.io/v3/1d1a8d816e9942e6850dca0c12b13cc2"
    print('blah')
    provider = HTTPProvider(url)
    w3 = Web3(provider)
    # first test how many ticks for 1 call
    v3contract = w3.eth.contract(abi=univ3_abi, address=address)
    override_address = to_checksum_address("0x" + "1" * 40)
    override_contract = w3.eth.contract(abi=helper_abi, address=override_address)

    txn_params = override_contract.functions.getTicks(address).build_transaction(
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


    end = time.time()

    print(f"time to retreive tick data: {end - start}")
    # print(txn[0:90000])

    # decode
    decoded_bytes_arr = abi.decode(("bytes[]", "(int128,int24)"), b, strict=False)
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
    




    # for i in decoded_ticks_arr:
    #     if i['liquidity_net'] == 0:
    #         print(i)
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
