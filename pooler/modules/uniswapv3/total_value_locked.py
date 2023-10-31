import functools
import json
import pathlib
import time
from typing import Union
from eth_abi import abi

import web3

from pooler.modules.uniswapv3.utils.constants \
import pair_contract_abi, current_node, max_gas_static_call
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

# load helper abi
helper_contract_abi = read_json_file(
    'pooler/tests/static/abi/UniV3Helper.json'
)


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
    override_address = Web3.to_checksum_address("0x" + "1" * 40)
    overrides = {
        override_address: {"code": "0x608080604052600436101561001357600080fd5b60003560e01c63802036f51461002857600080fd5b346106155760207ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc360112610615576004359073ffffffffffffffffffffffffffffffffffffffff82168203610615577fd0c93a7c00000000000000000000000000000000000000000000000000000000815260208160048173ffffffffffffffffffffffffffffffffffffffff86165afa90811561062257600091610975575b506040517f3850c7bd00000000000000000000000000000000000000000000000000000000815260408160048173ffffffffffffffffffffffffffffffffffffffff87165afa80156106225761092f575b508060020b15610900578060020b621b13d10560020b7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe061017361015d83610a1f565b9261016b60405194856109af565b808452610a1f565b013660208301376000918060020b7ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff276180560020b60081d60010b5b8060010b8260020b620d89e80560020b60081d60010b811361062e57604051907f5339c296000000000000000000000000000000000000000000000000000000008252600482015260208160248173ffffffffffffffffffffffffffffffffffffffff8a165afa908115610622576000916105eb575b50805b61026e575060010b617fff811461023f576001016101ad565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052601160045260246000fd5b8060ff6fffffffffffffffffffffffffffffffff8216156105df5750607f5b67ffffffffffffffff8216156105d55760ff7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc0818316011161023f5760ff167fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc0015b63ffffffff8216156105cb5760ff7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0818316011161023f5760ff167fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0015b61ffff8216156105c15760ff7ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff0818316011161023f5760ff167ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff0015b60ff8216156105b75760ff7ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff8818316011161023f5760ff167ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff8015b600f8216156105ad5760ff7ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc818316011161023f5760ff167ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc015b60038216156105a15760ff7ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe818316011161023f577ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe60ff6001921601915b1661054b575b60ff16906001821b18908360020b9060020b8360081b60020b1760020b028060020b90810361023f57807ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff27618839212158061053e575b610524575b50610226565b61053761053088610a37565b9787610a64565b523861051e565b50620d89e8811315610519565b60ff7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff818316011161023f5760ff167fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff016104c4565b9060019060021c6104be565b9060041c9061045f565b9060081c90610404565b9060101c906103a9565b9060201c9061034d565b9060401c906102ef565b90508160801c9061028d565b90506020813d60201161061a575b81610606602093836109af565b81010312610615575138610223565b600080fd5b3d91506105f9565b6040513d6000823e3d90fd5b50505061063a82610a1f565b9261064860405194856109af565b8284527fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe061067584610a1f565b0160005b8181106108ef57505060005b83811061075b578460405160208101916020825280518093526040820192602060408260051b8501019201906000945b8186106106c25784840385f35b9091927fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffc0858203018252835180519081835260005b828110610746575050602080837fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0601f85600085809860019a01015201160101950192019501949190916106b5565b806020809284010151828287010152016106f7565b6107658184610a64565b5160020b90604051917ff30dba9300000000000000000000000000000000000000000000000000000000835260048301526101008260248173ffffffffffffffffffffffffffffffffffffffff87165afa91821561062257600092610857575b506107d08185610a64565b516040519260801b602084015260e81b603083015260138252604082019180831067ffffffffffffffff84111761082857610823926040526108128288610a64565b5261081d8187610a64565b50610a37565b610685565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052604160045260246000fd5b909150610100813d610100116108e7575b8161087661010093836109af565b810103126106155780516fffffffffffffffffffffffffffffffff8116036106155760208101519081600f0b82036106155760808101518060060b03610615576108c260a082016109fe565b5060c081015163ffffffff8116036106155760e00151801515036106155790386107c5565b3d9150610868565b806060602080938901015201610679565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052601260045260246000fd5b6040813d60401161096d575b81610948604093836109af565b810103126106155760208161095f610966936109fe565b50016109f0565b503861011a565b3d915061093b565b90506020813d6020116109a7575b81610990602093836109af565b81010312610615576109a1906109f0565b386100c9565b3d9150610983565b90601f7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0910116810190811067ffffffffffffffff82111761082857604052565b51908160020b820361061557565b519073ffffffffffffffffffffffffffffffffffffffff8216820361061557565b67ffffffffffffffff81116108285760051b60200190565b7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff811461023f5760010190565b8051821015610a785760209160051b010190565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052603260045260246000fdfea2646970667358221220b066db1595cf7acb7b895611dc9837f3bd0731b073eef99e736694005439e20864736f6c63430008130033"}
    }
    override_contract = w3.eth.contract(abi=helper_contract_abi, address=override_address)
    
    # retrieve the max gas limit for the current block
    max_gas =  w3.eth.get_block('latest')['gasLimit'] - 1
    # create a web3 transaction object for a static state override call to the getTicks function of the helper
    txn_params = override_contract.functions.getTicks(Web3.to_checksum_address(pair_address)).build_transaction(
        {   
            "gas": 12345678987654323
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
