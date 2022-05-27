from functools import partial
from tenacity import retry, AsyncRetrying, stop_after_attempt, wait_random, wait_random_exponential, retry_if_exception_type
from typing import List
from web3 import Web3
from web3.datastructures import AttributeDict
from eth_utils import keccak
from web3._utils.events import get_event_data
from eth_abi.codec import ABICodec
import asyncio
import aiohttp
from redis_conn import provide_async_redis_conn_insta
from dynaconf import settings
import logging.config
import os
import math
import json
from bounded_pool_executor import BoundedThreadPoolExecutor
import threading
from concurrent.futures import as_completed
import aioredis
from async_limits.strategies import AsyncFixedWindowRateLimiter
from async_limits.storage import AsyncRedisStorage
from async_limits import parse_many as limit_parse_many
import time
from datetime import datetime, timedelta
from redis_keys import (
    uniswap_pair_contract_tokens_addresses, uniswap_pair_contract_tokens_data, uniswap_pair_cached_token_price,
    uniswap_pair_contract_V2_pair_data, uniswap_pair_cached_block_height_token_price
)
from helper_functions import (
    acquire_threading_semaphore
)

w3 = Web3(Web3.HTTPProvider(settings.RPC.MATIC[0]))
# TODO: Use async http provider once it is considered stable by the web3.py project maintainers
# web3_async = Web3(Web3.AsyncHTTPProvider(settings.RPC.MATIC[0]))

logger = logging.getLogger('PowerLoom|UniswapHelpers')
logger.setLevel(logging.DEBUG)
logger.handlers = [logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]

# Initialize rate limits when program starts
GLOBAL_RPC_RATE_LIMIT_STR = settings.RPC.rate_limit
PARSED_LIMITS = limit_parse_many(GLOBAL_RPC_RATE_LIMIT_STR)
LUA_SCRIPT_SHAS = None

# # # RATE LIMITER LUA SCRIPTS
SCRIPT_CLEAR_KEYS = """
        local keys = redis.call('keys', KEYS[1])
        local res = 0
        for i=1,#keys,5000 do
            res = res + redis.call(
                'del', unpack(keys, i, math.min(i+4999, #keys))
            )
        end
        return res
        """

SCRIPT_INCR_EXPIRE = """
        local current
        current = redis.call("incrby",KEYS[1],ARGV[2])
        if tonumber(current) == tonumber(ARGV[2]) then
            redis.call("expire",KEYS[1],ARGV[1])
        end
        return current
    """

# args = [value, expiry]
SCRIPT_SET_EXPIRE = """
    local keyttl = redis.call('TTL', KEYS[1])
    local current
    current = redis.call('SET', KEYS[1], ARGV[1])
    if keyttl == -2 then
        redis.call('EXPIRE', KEYS[1], ARGV[2])
    elseif keyttl ~= -1 then
        redis.call('EXPIRE', KEYS[1], keyttl)
    end
    return current
"""


# # # END RATE LIMITER LUA SCRIPTS


# KEEP INTERFACE ABIs CACHED IN MEMORY
def read_json_file(file_path: str):
    """Read given json file and return its content as a dictionary."""
    try:
        f_ = open(file_path, 'r')
    except Exception as e:
        logger.warning(f"Unable to open the {file_path} file")
        logger.error(e, exc_info=True)
        raise e
    else:
        json_data = json.loads(f_.read())
    return json_data


pair_contract_abi = read_json_file(f"abis/UniswapV2Pair.json")
erc20_abi = read_json_file('abis/IERC20.json')
router_contract_abi = read_json_file(f"abis/UniswapV2Router.json")
uniswap_trade_events_abi = read_json_file('abis/UniswapTradeEvents.json')

router_addr = settings.CONTRACT_ADDRESSES.IUNISWAP_V2_ROUTER
dai = settings.CONTRACT_ADDRESSES.DAI
usdt = settings.CONTRACT_ADDRESSES.USDT
weth = settings.CONTRACT_ADDRESSES.WETH

codec: ABICodec = w3.codec

UNISWAP_TRADE_EVENT_SIGS = {
    'Swap': "Swap(address,uint256,uint256,uint256,uint256,address)",
    'Mint': "Mint(address,uint256,uint256)",
    'Burn': "Burn(address,uint256,uint256,address)"
}


class RPCException(Exception):
    def __init__(self, request, response, underlying_exception, extra_info):
        self.request = request
        self.response = response
        self.underlying_exception: Exception = underlying_exception
        self.extra_info = extra_info

    def __str__(self):
        ret = {
            'request': self.request,
            'response': self.response,
            'extra_info': self.extra_info,
            'exception': None
        }
        if isinstance(self.underlying_exception, Exception):
            ret.update({'exception': self.underlying_exception.__str__()})
        return json.dumps(ret)

    def __repr__(self):
        return self.__str__()


# needs to be run only once
async def load_rate_limiter_scripts(redis_conn: aioredis.Redis):
    script_clear_keys_sha = await redis_conn.script_load(SCRIPT_CLEAR_KEYS)
    script_incr_expire = await redis_conn.script_load(SCRIPT_INCR_EXPIRE)
    return {
        "script_incr_expire": script_incr_expire,
        "script_clear_keys": script_clear_keys_sha
    }


# initiate all contracts
try:
    # instantiate UniswapV2Factory contract (using quick swap v2 factory address)
    quick_swap_uniswap_v2_factory_contract = w3.eth.contract(
        address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.IUNISWAP_V2_FACTORY),
        abi=read_json_file('./abis/IUniswapV2Factory.json')
    )

except Exception as e:
    quick_swap_uniswap_v2_factory_contract = None
    logger.error(e, exc_info=True)


def get_event_sig_and_abi(event_name):
    event_sig = '0x' + keccak(text=UNISWAP_TRADE_EVENT_SIGS.get(event_name, 'incorrect event name')).hex()
    abi = uniswap_trade_events_abi.get(event_name, 'incorrect event name')
    return event_sig, abi


def get_events_logs(contract_address, toBlock, fromBlock, topics, event_abi):
    event_log = w3.eth.get_logs({
        'address': Web3.toChecksumAddress(contract_address),
        'toBlock': toBlock,
        'fromBlock': fromBlock,
        'topics': topics
    })

    all_events = []
    for log in event_log:
        evt = get_event_data(codec, event_abi, log)
        all_events.append(evt)

    return all_events

async def get_block_details(ev_loop, block_number):
    try:
        block_details = dict()
        block_det_func = partial(w3.eth.get_block, int(block_number))
        block_details = await ev_loop.run_in_executor(func=block_det_func, executor=None)
        block_details = dict() if not block_details else block_details
    except Exception as e:
        logger.error('Error attempting to get block details of recent transaction timestamp %s: %s', block_number, e, exc_info=True)
        block_details = dict()
    finally:
        return block_details

async def store_price_at_block_range(begin_block, end_block, token0, token1, price, redis_conn: aioredis.Redis):
    """Store price at block range in redis."""

    block_prices = {}
    for i in range(begin_block, end_block + 1):
        block_prices[json.dumps({
            "price": price,
            "block_number": i,
            "timestamp": int(time.time())
        })]= i
        

    await redis_conn.zadd(
        name=uniswap_pair_cached_block_height_token_price.format(f"{token0}-{token1}"),
        mapping=block_prices
    )
    return len(block_prices)


async def extract_recent_transaction_logs(ev_loop, event_name, event_logs, pair_per_token_metadata, token0_price_map, token1_price_map):
    """
    Get trade value in USD "for each transaction"
    with amount of each token, txHash and account addresses
    """
    recent_transaction_logs = list()
    for log in event_logs:
        token0_amount = 0
        token1_amount = 0
        token1_swapped_usd = 0
        token0_swapped_usd = 0
        trade_amount_usd = 0
        if event_name == 'Swap':
            if log.args.get('amount1In') == 0:

                current0_swapped = log.args.get('amount0In') / 10 ** int(pair_per_token_metadata['token0']['decimals'])
                token0_amount = current0_swapped
                token0_swapped_usd = current0_swapped * token0_price_map.get(log["blockNumber"], list(token0_price_map.values())[0])
                
                current1_swapped = log.args.get('amount1Out') / 10 ** int(pair_per_token_metadata['token1']['decimals'])
                token1_amount = current1_swapped
                token1_swapped_usd = current1_swapped * token1_price_map.get(log["blockNumber"], list(token1_price_map.values())[0])
            elif log.args.get('amount0In') == 0:
                current0_swapped = log.args.get('amount0Out') / 10 ** int(pair_per_token_metadata['token0']['decimals']) 
                token0_amount = current0_swapped
                token0_swapped_usd = current0_swapped * token0_price_map.get(log["blockNumber"], list(token0_price_map.values())[0])

                current1_swapped = log.args.get('amount1In') / 10 ** int(pair_per_token_metadata['token1']['decimals'])
                token1_amount = current1_swapped
                token1_swapped_usd = current1_swapped * token1_price_map.get(log["blockNumber"], list(token1_price_map.values())[0])

        elif event_name == 'Mint' or event_name == 'Burn':
            current0_swapped = log.args.get('amount0') / 10 ** int(pair_per_token_metadata['token0']['decimals'])
            token0_amount = current0_swapped
            token0_swapped_usd = current0_swapped * token0_price_map.get(log["blockNumber"], list(token0_price_map.values())[0])
            
            current1_swapped = log.args.get('amount1') / 10 ** int(pair_per_token_metadata['token1']['decimals']) 
            token1_amount = current1_swapped
            token1_swapped_usd = current1_swapped * token1_price_map.get(log["blockNumber"], list(token1_price_map.values())[0])
        

        if event_name == 'Swap':
            trade_amount_usd = token1_swapped_usd if token1_swapped_usd else token0_swapped_usd
        elif event_name == 'Mint' or event_name == 'Burn':
            trade_amount_usd = token1_swapped_usd + token0_swapped_usd

        block_details = await get_block_details(ev_loop, log["blockNumber"])

        recent_transaction_logs.append({
            "sender": log.args.get("sender", ""),
            "to": log.args.get("to", ""),
            "transactionHash": log["transactionHash"].hex(),
            "logIndex": log["logIndex"],
            "blockNumber": log["blockNumber"],
            "event": log["event"],
            "token0_amount": token0_amount,
            "token1_amount": token1_amount,
            "trade_amount_usd": trade_amount_usd,
            "timestamp": block_details.get("timestamp", "")
        })

    return recent_transaction_logs


async def extract_trade_volume_data(ev_loop, event_name, event_logs: List[AttributeDict], redis_conn: aioredis.Redis, pair_per_token_metadata, token0_price_map, token1_price_map):
    log_topic_values = list()
    token0_swapped = 0
    token1_swapped = 0
    token0_swapped_usd = 0
    token1_swapped_usd = 0
    for log in event_logs:
        log_parent = log
        log = log.args
        topics = dict()
        for field in uniswap_trade_events_abi[event_name]['inputs']:
            field = field['name']
            topics[field] = log.get(field)
        topics['blockNumber'] = log_parent.get('blockNumber')
        log_topic_values.append(topics)

    for parsed_log_obj_values in log_topic_values:
        if event_name == 'Swap':
            if parsed_log_obj_values.get('amount1In') == 0:
            
                current0_swapped = parsed_log_obj_values.get('amount0In') / 10 ** int(pair_per_token_metadata['token0']['decimals'])
                token0_swapped += current0_swapped
                token0_swapped_usd += current0_swapped * token0_price_map.get(parsed_log_obj_values.get('blockNumber'), list(token0_price_map.values())[0])
                
                current1_swapped = parsed_log_obj_values.get('amount1Out') / 10 ** int(pair_per_token_metadata['token1']['decimals'])
                token1_swapped += current1_swapped
                token1_swapped_usd += current1_swapped * token1_price_map.get(parsed_log_obj_values.get('blockNumber'), list(token1_price_map.values())[0])

            elif parsed_log_obj_values.get('amount0In') == 0:

                current0_swapped = parsed_log_obj_values.get('amount0Out') / 10 ** int(pair_per_token_metadata['token0']['decimals']) 
                token0_swapped += current0_swapped
                token0_swapped_usd += current0_swapped * token0_price_map.get(parsed_log_obj_values.get('blockNumber'), list(token0_price_map.values())[0])

                current1_swapped = parsed_log_obj_values.get('amount1In') / 10 ** int(pair_per_token_metadata['token1']['decimals'])
                token1_swapped += current1_swapped
                token1_swapped_usd += current1_swapped * token1_price_map.get(parsed_log_obj_values.get('blockNumber'), list(token1_price_map.values())[0])


        elif event_name == 'Mint' or event_name == 'Burn':
            
            current0_swapped = parsed_log_obj_values.get('amount0') / 10 ** int(pair_per_token_metadata['token0']['decimals'])
            token0_swapped += current0_swapped
            token0_swapped_usd += current0_swapped * token0_price_map.get(parsed_log_obj_values.get('blockNumber'), list(token0_price_map.values())[0])
            
            current1_swapped = parsed_log_obj_values.get('amount1') / 10 ** int(pair_per_token_metadata['token1']['decimals']) 
            token1_swapped += current1_swapped
            token1_swapped_usd += current1_swapped * token1_price_map.get(parsed_log_obj_values.get('blockNumber'), list(token1_price_map.values())[0])


    #TODO: instead of fetching the price from the redis cache, fetch price from rpc using block_number
    # get conversion
    trade_volume_usd = 0
    trade_fee_usd = 0
    
    #Add Recent Transactions Logs
    recent_transaction_logs = await extract_recent_transaction_logs(ev_loop, event_name, event_logs, pair_per_token_metadata, token0_price_map, token1_price_map)


    # if event is 'Swap' then only add single token in total volume calculation
    if event_name == 'Swap':
        
        # set one side token value in swap case
        trade_volume_usd = token1_swapped_usd if token1_swapped_usd else token0_swapped_usd

        # calculate uniswap LP fee
        trade_fee_usd = token1_swapped_usd  * 0.003 if token1_swapped_usd else token0_swapped_usd * 0.003 # uniswap LP fee rate

        return {
            'totalTradesUSD': trade_volume_usd,
            'totalFeeUSD': trade_fee_usd,
            'token0TradeVolume': token0_swapped,
            'token1TradeVolume': token1_swapped,
            'token0TradeVolumeUSD': token0_swapped_usd,
            'token1TradeVolumeUSD': token1_swapped_usd,
            'recent_transaction_logs': recent_transaction_logs
        }
    

    trade_volume_usd = token0_swapped_usd + token1_swapped_usd
    
    return {
        'totalTradesUSD': trade_volume_usd,
        'token0TradeVolume': token0_swapped,
        'token1TradeVolume': token1_swapped,
        'token0TradeVolumeUSD': token0_swapped_usd,
        'token1TradeVolumeUSD': token1_swapped_usd,
        'recent_transaction_logs': recent_transaction_logs
    }


# get allPairLength
def get_all_pair_length():
    return quick_swap_uniswap_v2_factory_contract.functions.allPairsLength().call()


# call allPair by index number
@acquire_threading_semaphore
def get_pair_by_index(index, semaphore=None):
    if not index:
        index = 0
    pair = quick_swap_uniswap_v2_factory_contract.functions.allPairs(index).call()
    return pair


# get list of allPairs using allPairsLength
def get_all_pairs():
    all_pairs = []
    all_pair_length = get_all_pair_length()
    logger.debug(f"All pair length: {all_pair_length}, accumulating all pairs addresses, please wait...")

    # declare semaphore and executor
    sem = threading.BoundedSemaphore(settings.UNISWAP_FUNCTIONS.THREADING_SEMAPHORE)
    with BoundedThreadPoolExecutor(max_workers=settings.UNISWAP_FUNCTIONS.SEMAPHORE_WORKERS) as executor:
        future_to_pairs_addr = {executor.submit(
            get_pair_by_index,
            index=index,
            semaphore=sem
        ): index for index in range(all_pair_length)}
    added = 0
    for future in as_completed(future_to_pairs_addr):
        pair_addr = future_to_pairs_addr[future]
        try:
            rj = future.result()
        except Exception as exc:
            logger.error(f"Error getting address of pair against index: {pair_addr}")
            logger.error(exc, exc_info=True)
            continue
        else:
            if rj:
                all_pairs.append(rj)
                added += 1
                if added % 1000 == 0:
                    logger.debug(f"Accumulated {added} pair addresses")
            else:
                logger.debug(f"Skipping pair address at index: {pair_addr}")
    logger.debug(f"Cached a total {added} pair addresses")
    return all_pairs


# get list of allPairs using allPairsLength and write to file
def get_all_pairs_and_write_to_file():
    try:
        all_pairs = get_all_pairs()
        if not os.path.exists('static/'):
            os.makedirs('static/')

        with open('static/cached_pair_addresses2.json', 'w') as f:
            json.dump(all_pairs, f)
        return all_pairs
    except Exception as e:
        logger.error(e, exc_info=True)
        raise e


async def get_maker_pair_data(prop):
    prop = prop.lower()
    if prop.lower() == "name":
        return "Maker"
    elif prop.lower() == "symbol":
        return "MKR"
    else:
        return "Maker"

async def get_pair_per_token_metadata(
        pair_contract_obj, pair_address,
        loop: asyncio.AbstractEventLoop,
        redis_conn: aioredis.Redis
):
    """
        returns information on the tokens contained within a pair contract - name, symbol, decimals of token0 and token1
        also returns pair symbol by concatenating {token0Symbol}-{token1Symbol}
    """
    try:
        pair_address = Web3.toChecksumAddress(pair_address)
        pairTokensAddresses = await redis_conn.hgetall(uniswap_pair_contract_tokens_addresses.format(pair_address))
        if pairTokensAddresses:
            token0Addr = Web3.toChecksumAddress(pairTokensAddresses[b"token0Addr"].decode('utf-8'))
            token1Addr = Web3.toChecksumAddress(pairTokensAddresses[b"token1Addr"].decode('utf-8'))
        else:
            # run in loop's default executor
            pfunc_0 = partial(pair_contract_obj.functions.token0().call)
            token0Addr = await loop.run_in_executor(func=pfunc_0, executor=None)
            pfunc_1 = partial(pair_contract_obj.functions.token1().call)
            token1Addr = await loop.run_in_executor(func=pfunc_1, executor=None)
            token0Addr = Web3.toChecksumAddress(token0Addr)
            token1Addr = Web3.toChecksumAddress(token1Addr)
            await redis_conn.hset(
                name=uniswap_pair_contract_tokens_addresses.format(pair_address),
                mapping={
                    'token0Addr': token0Addr,
                    'token1Addr': token1Addr
                })
        # token0 contract
        token0 = w3.eth.contract(
            address=Web3.toChecksumAddress(token0Addr),
            abi=erc20_abi
        )
        # token1 contract
        token1 = w3.eth.contract(
            address=Web3.toChecksumAddress(token1Addr),
            abi=erc20_abi
        )
        pair_tokens_data = await redis_conn.hgetall(uniswap_pair_contract_tokens_data.format(pair_address))
        if pair_tokens_data:
            token0_decimals = pair_tokens_data[b"token0_decimals"].decode('utf-8')
            token1_decimals = pair_tokens_data[b"token1_decimals"].decode('utf-8')
            token0_symbol = pair_tokens_data[b"token0_symbol"].decode('utf-8')
            token1_symbol = pair_tokens_data[b"token1_symbol"].decode('utf-8')
            token0_name = pair_tokens_data[b"token0_name"].decode('utf-8')
            token1_name = pair_tokens_data[b"token1_name"].decode('utf-8')
        else:
            executor_gather = list()
            if(Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.MAKER) == Web3.toChecksumAddress(token0Addr)):
                executor_gather.append(get_maker_pair_data('name'))
                executor_gather.append(get_maker_pair_data('symbol'))
            else:
                executor_gather.append(loop.run_in_executor(func=token0.functions.name().call, executor=None))
                executor_gather.append(loop.run_in_executor(func=token0.functions.symbol().call, executor=None))
            executor_gather.append(loop.run_in_executor(func=token0.functions.decimals().call, executor=None))


            if(Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.MAKER) == Web3.toChecksumAddress(token1Addr)):
                executor_gather.append(get_maker_pair_data('name'))
                executor_gather.append(get_maker_pair_data('symbol'))
            else:
                executor_gather.append(loop.run_in_executor(func=token1.functions.name().call, executor=None))
                executor_gather.append(loop.run_in_executor(func=token1.functions.symbol().call, executor=None))
            executor_gather.append(loop.run_in_executor(func=token1.functions.decimals().call, executor=None))

            [
                token0_name, token0_symbol, token0_decimals,
                token1_name, token1_symbol, token1_decimals
            ] = await asyncio.gather(*executor_gather)

            await redis_conn.hset(
                name=uniswap_pair_contract_tokens_data.format(pair_address),
                mapping={
                    "token0_name": token0_name,
                    "token0_symbol": token0_symbol,
                    "token0_decimals": token0_decimals,
                    "token1_name": token1_name,
                    "token1_symbol": token1_symbol,
                    "token1_decimals": token1_decimals,
                    "pair_symbol": f"{token0_symbol}-{token1_symbol}"
                }
            )
            # print(f"pair_symbol {token0_symbol}-{token1_symbol}")
        # TODO: formalize return structure in a pydantic model for better readability
        return {
            'token0': {
                'address': token0Addr,
                'name': token0_name,
                'symbol': token0_symbol,
                'decimals': token0_decimals
            },
            'token1': {
                'address': token1Addr,
                'name': token1_name,
                'symbol': token1_symbol,
                'decimals': token1_decimals
            },
            'pair': {
                'symbol': f'{token0_symbol}-{token1_symbol}'
            }
        }
    except Exception as e:
        # this will be retried in next cycle
        logger.error(f"RPC error while fetcing metadata for pair {pair_address}, error_msg:{e}", exc_info=True)
        return {}

async def get_token_price_at_block_height(token_contract_obj, token_metadata, block_height, loop: asyncio.AbstractEventLoop, redis_conn, debug_log=True):
    """
        returns the price of a token at a given block height
    """
    try:
        token_price = 0
        
        if block_height != 'latest':
            cached_price = await redis_conn.zrangebyscore(
                name=uniswap_pair_cached_block_height_token_price.format(Web3.toChecksumAddress(token_metadata['address'])),
                min=int(block_height),
                max=int(block_height)
            )
            cached_price = cached_price[0].decode('utf-8') if len(cached_price) > 0 else False
            if cached_price:
                cached_price = json.loads(cached_price)
                token_price = cached_price['price'] 
                return token_price
        
        # else fetch from rpc
        stable_coins_addresses = {
            "USDC": Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDC),
            "DAI": Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.DAI),
            "USDT": Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDT),
        }
        stable_coins_decimals = {
            "USDT": 6,
            "DAI": 18,
            "USDC": 6
        }
        nonStable_coins_addresses = {
            Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.agEUR): {
                "token0": Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.agEUR),
                "token1": Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.FEI),
                "decimals": 18
            },
            Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.SYN): {
                "token0": Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.SYN),
                "token1": Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.FRAX),
                "decimals": 18
            }
        }

        # this is used to avoid INSUFFICIENT_INPUT_AMOUNT error 
        token_amount_multiplier = 10 ** 18
        
        # check if token is a stable coin if so then ignore price fetch call
        if Web3.toChecksumAddress(token_metadata['address']) in list(stable_coins_addresses.values()):
                token_price = 1
                if debug_log:
                    logger.debug(f"Ignored Stablecoin calculation for token0: {token_metadata['symbol']} - WETH - USDT conversion: {token_price}")

        # check if token has no pair with stablecoin and weth if so then use hardcoded path 
        elif nonStable_coins_addresses.get(Web3.toChecksumAddress(token_metadata['address'])):
            contract_metadata = nonStable_coins_addresses.get(Web3.toChecksumAddress(token_metadata['address']))
            priceFunction_token0 = partial(token_contract_obj.functions.getAmountsOut(
                10 ** int(contract_metadata['decimals']), 
                [
                    contract_metadata['token0'],
                    contract_metadata['token1'],
                    Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDC)
                ]
            ).call, block_identifier=block_height)
            temp_token_price = await loop.run_in_executor(func=priceFunction_token0, executor=None)
            if temp_token_price:
                temp_token_price = temp_token_price[2]/10**stable_coins_decimals['USDC'] if temp_token_price[2] !=0 else 0  #USDC decimals
                token_price = temp_token_price if token_price < temp_token_price else token_price

        # 1. if is not equals to weth then check its price against each stable coin take out heighest
        # 2. if price is still 0/None then pass path as token->weth-usdt
        # 3. if price is still 0/None then increase token amount in path (token->weth-usdc) 
        elif Web3.toChecksumAddress(token_metadata['address']) \
                != Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH):
            
            # iterate over all stable coin to find price
            stable_coins_len = len(stable_coins_addresses)
            for key, value in stable_coins_addresses.items():
                try:
                    priceFunction_token0 = partial(token_contract_obj.functions.getAmountsOut(
                        10 ** int(token_metadata['decimals']), 
                        [
                            Web3.toChecksumAddress(token_metadata['address']),
                            value
                        ]
                    ).call, block_identifier=block_height)
                    temp_token_price = await loop.run_in_executor(func=priceFunction_token0, executor=None)
                    if temp_token_price:
                        temp_token_price = temp_token_price[1]/10**stable_coins_decimals[key] if temp_token_price[1] !=0 else 0  #USDT decimals
                        token_price = temp_token_price if token_price < temp_token_price else token_price
                except Exception as error:
                    # if reverted then it means token do not have pair with this stablecoin, try another
                    if "execution reverted" in str(error):
                        temp_token_price = 0
                        pass
                else:
                    # if there was no exception and price is still 0 then increase token amount in path (token->stablecoin)
                    if temp_token_price == 0:
                        priceFunction_token0 = partial(token_contract_obj.functions.getAmountsOut(
                            10 ** int(token_metadata['decimals']) * token_amount_multiplier, 
                            [
                                Web3.toChecksumAddress(token_metadata['address']),
                                value
                            ]
                        ).call, block_identifier=block_height)
                        temp_token_price = await loop.run_in_executor(func=priceFunction_token0, executor=None)
                        if temp_token_price:
                            temp_token_price = temp_token_price[1]/10**stable_coins_decimals[key] if temp_token_price[1] !=0 else 0  #USDT decimals
                            temp_token_price = temp_token_price/token_amount_multiplier
                            token_price = temp_token_price if token_price < temp_token_price else token_price
                            
                
                stable_coins_len -= 1
                if stable_coins_len <= 0:
                    break
            
            # After iterating over all stable coin, check if path conversion by token->weth->usdt give a higher price of token
            # if so then replace it, as for some tokens we get accurate price by token->weth->usdt path only
            try:
                priceFunction_token0 = partial(token_contract_obj.functions.getAmountsOut(
                    10 ** int(token_metadata['decimals']), 
                    [
                        Web3.toChecksumAddress(token_metadata['address']),
                        Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH),
                        Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDT)
                    ]
                ).call, block_identifier=block_height)
                temp_token_price = await loop.run_in_executor(func=priceFunction_token0, executor=None)

                if temp_token_price:
                    temp_token_price = temp_token_price[2]/10**stable_coins_decimals["USDT"] if temp_token_price[2] !=0 else 0  #USDT decimals
                    token_price = temp_token_price if token_price < temp_token_price else token_price
            except Exception as error:
                # there might be INSUFFICIENT_INPUT_AMOUNT/execution_reverted error which can break program flow, so pass it
                pass

            # after going through all stablecoins and weth conversion if price is still 0
            # then increase token amount in path (token->weth-usdt)
            if token_price == 0:
                priceFunction_token0 = partial(token_contract_obj.functions.getAmountsOut(
                    10 ** int(token_metadata['decimals']) * token_amount_multiplier, 
                    [
                        Web3.toChecksumAddress(token_metadata['address']),
                        Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH),
                        Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDT)
                    ]
                ).call, block_identifier=block_height)
                temp_token_price = await loop.run_in_executor(func=priceFunction_token0, executor=None)

                if temp_token_price:
                    temp_token_price = temp_token_price[2]/10**stable_coins_decimals["USDT"] if temp_token_price[2] !=0 else 0  #USDT decimals
                    temp_token_price = temp_token_price/token_amount_multiplier                   
                    token_price = temp_token_price if token_price < temp_token_price else token_price
        
            if debug_log:
                logger.debug(f"Calculated price for token0: {token_metadata['symbol']} - stablecoin conversion: {token_price}")
        
        # if token is weth then directly check its price against stable coin
        else:    
            priceFunction_token0 = partial(token_contract_obj.functions.getAmountsOut(
                10 ** int(token_metadata['decimals']), [
                    Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH),
                    Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDT)]
            ).call, block_identifier=block_height)
            token_price = await loop.run_in_executor(func=priceFunction_token0, executor=None)
            token_price = token_price[1]/10**stable_coins_decimals["USDT"] #USDT decimals
            if debug_log:
                logger.debug(f"Calculated prices for token0: {token_metadata['symbol']} - USDT conversion: {token_price}")

        # cache price at height
        if block_height != 'latest':
            await redis_conn.zadd(
                name=uniswap_pair_cached_block_height_token_price.format(Web3.toChecksumAddress(token_metadata['address'])),
                mapping={json.dumps({
                    'blockHeight': block_height,
                    'price': token_price
                }): int(block_height)} # timestamp so zset do not ignore same height on multiple heights
            )
    except Exception as err:
        logger.error(f"Error: failed to fetch token price | error_msg: {str(err)} | contract: {token_metadata['address']}")
    finally:
        return float(token_price)


# asynchronously get liquidity of each token reserve
@retry(
    reraise=True, 
    retry=retry_if_exception_type(RPCException), 
    wait=wait_random_exponential(multiplier=1, max=10), 
    stop=stop_after_attempt(settings.UNISWAP_FUNCTIONS.RETRIAL_ATTEMPTS)
)
async def get_liquidity_of_each_token_reserve_async(
        loop: asyncio.AbstractEventLoop,
        rate_limit_lua_script_shas: dict,
        pair_address,
        redis_conn: aioredis.Redis,
        block_identifier='latest',
        fetch_timestamp=False
):
    try:
        pair_address = Web3.toChecksumAddress(pair_address)
        # pair contract
        pair = w3.eth.contract(
            address=pair_address,
            abi=pair_contract_abi
        )
        router_contract_obj = w3.eth.contract(
            address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.IUNISWAP_V2_ROUTER),
            abi=router_contract_abi
        )
        # logger.debug('Got sha load results for rate limiter scripts: %s', lua_scripts)
        redis_storage = AsyncRedisStorage(rate_limit_lua_script_shas, redis_conn)
        custom_limiter = AsyncFixedWindowRateLimiter(redis_storage)
        limit_incr_by = 1  # score to be incremented for each request
        if fetch_timestamp:
            limit_incr_by += 1
        app_id = settings.RPC.MATIC[0].split('/')[
            -1]  # future support for loadbalancing over multiple MaticVigil RPC appID
        key_bits = [app_id, 'eth_call']  # TODO: add unique elements that can identify a request
        can_request = False
        rate_limit_exception = False
        retry_after = 1
        response = None
        for each_lim in PARSED_LIMITS:
            # window_stats = custom_limiter.get_window_stats(each_lim, key_bits)
            # local_app_cacher_logger.debug(window_stats)
            # rest_logger.debug('Limit %s expiry: %s', each_lim, each_lim.get_expiry())
            # async limits rate limit check
            # if rate limit checks out then we call
            try:
                if await custom_limiter.hit(each_lim, limit_incr_by, *[key_bits]) is False:
                    window_stats = await custom_limiter.get_window_stats(each_lim, key_bits)
                    reset_in = 1 + window_stats[0]
                    # if you need information on back offs
                    retry_after = reset_in - int(time.time())
                    retry_after = (datetime.now() + timedelta(0, retry_after)).isoformat()
                    can_request = False
                    break  # make sure to break once false condition is hit
            except (
                    aioredis.exceptions.ConnectionError, aioredis.exceptions.TimeoutError,
                    aioredis.exceptions.ResponseError
            ) as e:
                # shit can happen while each limit check call hits Redis, handle appropriately
                logger.debug('Bypassing rate limit check for appID because of Redis exception: ' + str(
                    {'appID': app_id, 'exception': e}))
            except Exception as e:
                logger.error('Caught exception on rate limiter operations: %s', e, exc_info=True)
                raise
            else:
                can_request = True
        if can_request:
            if fetch_timestamp:
                block_det_func = partial(w3.eth.get_block, block_identifier)
                try:
                    block_details = await loop.run_in_executor(func=block_det_func, executor=None)
                except:
                    block_details = None
            else:
                block_details = None
            pair_per_token_metadata = await get_pair_per_token_metadata(
                pair_contract_obj=pair,
                pair_address=pair_address,
                loop=loop,
                redis_conn=redis_conn
            )
            

            pfunc_get_reserves = partial(pair.functions.getReserves().call, block_identifier=block_identifier)
            async for attempt in AsyncRetrying(reraise=True, stop=stop_after_attempt(3), wait=wait_random(1, 2)):
                with attempt:
                    executor_gather = list()
                    executor_gather.append(loop.run_in_executor(func=pfunc_get_reserves, executor=None))
                    executor_gather.append(get_token_price_at_block_height(router_contract_obj, pair_per_token_metadata['token0'], block_identifier, loop, redis_conn))
                    executor_gather.append(get_token_price_at_block_height(router_contract_obj, pair_per_token_metadata['token1'], block_identifier, loop, redis_conn))
                    [
                        reserves, token0Price, token1Price
                    ] = await asyncio.gather(*executor_gather)
                    if reserves and token0Price and token1Price:
                        break
            token0_addr = pair_per_token_metadata['token0']['address']
            token1_addr = pair_per_token_metadata['token1']['address']
            token0_decimals = pair_per_token_metadata['token0']['decimals']
            token1_decimals = pair_per_token_metadata['token1']['decimals']
            
            token0Amount = reserves[0] / 10 ** int(token0_decimals)
            token1Amount = reserves[1] / 10 ** int(token1_decimals)
            
            # logger.debug(f"Decimals of token0: {token0_decimals}, Decimals of token1: {token1_decimals}")
            logger.debug("Token0: %s, Reserves: %s | Token1: %s, Reserves: %s", token0_addr, token0Amount, token1_addr, token1Amount)

            token0USD = 0
            token1USD = 0
            if token0Price:
                token0USD = token0Amount * token0Price
            else:
                logger.error(f"Liquidity: Could not find token0 price for {pair_per_token_metadata['token0']['symbol']}-USDT, setting it to 0")
            
            if token1Price:
                token1USD = token1Amount * token1Price
            else:
                logger.error(f"Liquidity: Could not find token1 price for {pair_per_token_metadata['token1']['symbol']}-USDT, setting it to 0")
                

            return {
                'token0': token0Amount,
                'token1': token1Amount,
                'token0USD': token0USD,
                'token1USD': token1USD,
                'timestamp': None if not block_details else block_details.timestamp
            }
        else:
            raise RPCException(request={"contract": pair_address, "block_identifier": block_identifier}, 
            response={}, underlying_exception=None, 
            extra_info={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get async liquidity reserves"})
    except Exception as exc:
        logger.error("error at async_get_liquidity_of_each_token_reserve fn: %s", exc, exc_info=True)
        # snapshot constructor expect exception and handle it with queue
        raise exc


async def get_trade_volume_epoch_price_map(
        loop,
        rate_limit_lua_script_shas: dict,
        to_block, from_block,
        token_metadata,
        redis_conn: aioredis.Redis,
        debug_log=False
):
    #ev_loop = asyncio.get_running_loop()
    # # # prepare for rate limit check
    router_contract_obj = w3.eth.contract(
        address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.IUNISWAP_V2_ROUTER),
        abi=router_contract_abi
    )
    redis_storage = AsyncRedisStorage(rate_limit_lua_script_shas, redis_conn)
    custom_limiter = AsyncFixedWindowRateLimiter(redis_storage)
    limit_incr_by = 1  # score to be incremented for each request
    app_id = settings.RPC.MATIC[0].split('/')[
        -1]  # future support for loadbalancing over multiple MaticVigil RPC appID
    key_bits = [app_id, 'eth_call']  # TODO: add unique elements that can identify a request
    
    price_map = {}
    for block in range(from_block, to_block + 1):
        if block != 'latest':
            cached_price = await redis_conn.zrangebyscore(
                name=uniswap_pair_cached_block_height_token_price.format(Web3.toChecksumAddress(token_metadata['address'])),
                min=int(block),
                max=int(block)
            )
            cached_price = cached_price[0].decode('utf-8') if len(cached_price) > 0 else False
            if cached_price:
                cached_price = json.loads(cached_price)
                price_map[block] = cached_price['price']
                continue

        # TODO: refactor rate limit check into something modular and easier to use
        # # # rate limit check - begin
        can_request = False
        rate_limit_exception = False
        retry_after = 1
        response = None
        for each_lim in PARSED_LIMITS:
            # window_stats = custom_limiter.get_window_stats(each_lim, key_bits)
            # local_app_cacher_logger.debug(window_stats)
            # logger.debug('Limit %s expiry: %s', each_lim, each_lim.get_expiry())
            try:
                if await custom_limiter.hit(each_lim, limit_incr_by, *[key_bits]) is False:
                    window_stats = await custom_limiter.get_window_stats(each_lim, key_bits)
                    reset_in = 1 + window_stats[0]
                    # if you need information on back offs
                    retry_after = reset_in - int(time.time())
                    retry_after = (datetime.now() + timedelta(0, retry_after)).isoformat()
                    can_request = False
                    break  # make sure to break once false condition is hit
            except (
                    aioredis.exceptions.ConnectionError, aioredis.exceptions.ResponseError,
                    aioredis.exceptions.RedisError, Exception
            ) as e:
                # shit can happen while each limit check call hits Redis, handle appropriately
                logger.debug('Bypassing rate limit check for appID because of Redis exception: ' + str(
                    {'appID': app_id, 'exception': e}))
            else:
                can_request = True
        # # # rate limit check - end
        if can_request:
            try:
                async for attempt in AsyncRetrying(reraise=True, stop=stop_after_attempt(3), wait=wait_random(1, 2)):
                    with attempt:
                        price = await get_token_price_at_block_height(router_contract_obj, token_metadata, block, loop, redis_conn, debug_log)
                        price_map[block] = price
                        if price:
                            break
            except Exception as err:
                # pair_contract price can't retrieved, this is mostly with sepcific coins log it and fetch price for newer ones
                logger.error(f"Failed to fetch token price | error_msg: {str(err)} | epoch: {to_block}-{from_block}", exc_info=True)
        else:
            logger.error('Trade Volume block map: I cant request, retry after sometime')
    
    return price_map


# asynchronously get trades on a pair contract
@retry(
    reraise=True, 
    retry=retry_if_exception_type(RPCException), 
    wait=wait_random_exponential(multiplier=1, max=10), 
    stop=stop_after_attempt(settings.UNISWAP_FUNCTIONS.RETRIAL_ATTEMPTS)
)
async def get_pair_contract_trades_async(
    ev_loop: asyncio.AbstractEventLoop,
    rate_limit_lua_script_shas: dict,
    pair_address,
    from_block,
    to_block,
    redis_conn: aioredis.Redis,
    fetch_timestamp=True
):
    try:
        pair_address = Web3.toChecksumAddress(pair_address)
        # pair contract
        pair = w3.eth.contract(
            address=pair_address,
            abi=pair_contract_abi
        )
        redis_storage = AsyncRedisStorage(rate_limit_lua_script_shas, redis_conn)
        custom_limiter = AsyncFixedWindowRateLimiter(redis_storage)
        limit_incr_by = 3  # be honest, we will make 3 eth_getLogs queries here
        app_id = settings.RPC.MATIC[0].split('/')[
            -1]  # future support for loadbalancing over multiple MaticVigil RPC appID
        key_bits = [app_id, 'eth_logs']  # TODO: add unique elements that can identify a request
        can_request = False
        rate_limit_exception = False
        retry_after = 1
        response = None
        for each_lim in PARSED_LIMITS:
            # window_stats = custom_limiter.get_window_stats(each_lim, key_bits)
            # local_app_cacher_logger.debug(window_stats)
            # rest_logger.debug('Limit %s expiry: %s', each_lim, each_lim.get_expiry())
            # async limits rate limit check
            # if rate limit checks out then we call
            try:
                if await custom_limiter.hit(each_lim, limit_incr_by, *[key_bits]) is False:
                    window_stats = await custom_limiter.get_window_stats(each_lim, key_bits)
                    reset_in = 1 + window_stats[0]
                    # if you need information on back offs
                    retry_after = reset_in - int(time.time())
                    retry_after = (datetime.now() + timedelta(0, retry_after)).isoformat()
                    can_request = False
                    break  # make sure to break once false condition is hit
            except (
                aioredis.exceptions.ConnectionError, aioredis.exceptions.ResponseError,
                aioredis.exceptions.RedisError, Exception
            ) as e:
                # shit can happen while each limit check call hits Redis, handle appropriately
                logger.debug('Bypassing rate limit check for appID because of Redis exception: ' + str(
                    {'appID': app_id, 'exception': e}))
            else:
                can_request = True
        if can_request:
            if fetch_timestamp:
                # logger.debug('Attempting to get block details of to_block %s', to_block)
                block_det_func = partial(w3.eth.get_block, to_block)
                try:
                    block_details = await ev_loop.run_in_executor(func=block_det_func, executor=None)
                except Exception as e:
                    logger.error('Error attempting to get block details of to_block %s: %s', to_block, e, exc_info=True)
                    block_details = None
            else:
                # logger.debug('Not attempting to get block details of to_block %s', to_block)
                block_details = None
            pair_per_token_metadata = await get_pair_per_token_metadata(
                pair_contract_obj=pair,
                pair_address=pair_address,
                loop=ev_loop,
                redis_conn=redis_conn
            )
            token0_price_map, token1_price_map = await asyncio.gather(
                get_trade_volume_epoch_price_map(loop=ev_loop, rate_limit_lua_script_shas=rate_limit_lua_script_shas, to_block=to_block, from_block=from_block, token_metadata=pair_per_token_metadata['token0'], redis_conn=redis_conn),
                get_trade_volume_epoch_price_map(loop=ev_loop, rate_limit_lua_script_shas=rate_limit_lua_script_shas, to_block=to_block, from_block=from_block, token_metadata=pair_per_token_metadata['token1'], redis_conn=redis_conn)
            )
            event_log_fetch_coros = list()
            for trade_event_name in ['Swap', 'Mint', 'Burn']:
                event_sig, event_abi = get_event_sig_and_abi(trade_event_name)
                pfunc_get_event_logs = partial(
                    get_events_logs, **{
                        'contract_address': pair_address,
                        'toBlock': to_block,
                        'fromBlock': from_block,
                        'topics': [event_sig],
                        'event_abi': event_abi
                    }
                )
                event_log_fetch_coros.append(ev_loop.run_in_executor(func=pfunc_get_event_logs, executor=None))
            [
                swap_event_logs, mint_event_logs, burn_event_logs
            ] = await asyncio.gather(*event_log_fetch_coros)
            logs_ret = {
                'Swap': swap_event_logs,
                'Mint': mint_event_logs,
                'Burn': burn_event_logs
            }
            # extract total trade from them
            rets = dict()
            for trade_event_name in ['Swap', 'Mint', 'Burn']:
                # print(f'Event {trade_event_name} logs: ', logs_ret[trade_event_name])
                rets.update({
                    trade_event_name: {
                        'logs': [{
                            **dict(k.args),
                            "transactionHash": k["transactionHash"].hex(),
                            "logIndex": k["logIndex"],
                            "blockNumber": k["blockNumber"],
                            "event": k["event"]
                        } for k in logs_ret[trade_event_name]],
                        'trades': await extract_trade_volume_data(
                            ev_loop=ev_loop,
                            event_name=trade_event_name,
                            # event_logs=logs_ret[trade_event_name],
                            event_logs=logs_ret[trade_event_name],
                            redis_conn=redis_conn,
                            pair_per_token_metadata=pair_per_token_metadata,
                            token0_price_map=token0_price_map, 
                            token1_price_map=token1_price_map
                        )
                    }
                })
            max_block_timestamp = None if not block_details else block_details.timestamp
            rets.update({'timestamp': max_block_timestamp})
            return rets
        else:
            raise RPCException(request={"contract": pair_address, "fromBlock": from_block, "toBlock": to_block}, 
            response={}, underlying_exception=None, 
            extra_info={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get async trade volume"})
    except Exception as exc:
        logger.error("error at get_pair_contract_trades_async fn: %s", exc, exc_info=True)
        # snapshot constructor expect exception and handle it with queue
        raise exc


# get liquidity of each token reserve
def get_liquidity_of_each_token_reserve(pair_address, block_identifier='latest'):
    # logger.debug("Pair Data:")
    pair_address = Web3.toChecksumAddress(pair_address)
    # pair contract
    pair = w3.eth.contract(
        address=pair_address,
        abi=pair_contract_abi
    )

    token0Addr = pair.functions.token0().call()
    token1Addr = pair.functions.token1().call()
    # async limits rate limit check
    # if rate limit checks out then we call
    # introduce block height in get reserves
    reservers = pair.functions.getReserves().call(block_identifier=block_identifier)
    logger.debug(f"Token0: {token0Addr}, Reservers: {reservers[0]}")
    logger.debug(f"Token1: {token1Addr}, Reservers: {reservers[1]}")

    # toke0 contract
    token0 = w3.eth.contract(
        address=Web3.toChecksumAddress(token0Addr),
        abi=erc20_abi
    )
    # toke1 contract
    token1 = w3.eth.contract(
        address=Web3.toChecksumAddress(token1Addr),
        abi=erc20_abi
    )

    token0_decimals = token0.functions.decimals().call()
    token1_decimals = token1.functions.decimals().call()

    logger.debug(f"Decimals of token1: {token1_decimals}, Decimals of token1: {token0_decimals}")
    logger.debug(
        f"reservers[0]/10**token0_decimals: {reservers[0] / 10 ** token0_decimals}, reservers[1]/10**token1_decimals: {reservers[1] / 10 ** token1_decimals}")

    return {"token0": reservers[0] / 10 ** token0_decimals, "token1": reservers[1] / 10 ** token1_decimals}


def get_pair(token0, token1):
    token0 = w3.toChecksumAddress(token0)
    token1 = w3.toChecksumAddress(token1)
    pair = quick_swap_uniswap_v2_factory_contract.functions.getPair(token0, token1).call()
    return pair


async def get_aiohttp_cache() -> aiohttp.ClientSession:
    basic_rpc_connector = aiohttp.TCPConnector(limit=settings['rlimit']['file_descriptors'])
    aiohttp_client_basic_rpc_session = aiohttp.ClientSession(connector=basic_rpc_connector)
    return aiohttp_client_basic_rpc_session

if __name__ == '__main__':
    # here instead of calling get pair we can directly use cached all pair addresses
    # dai = "0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063"
    # gns = "0xE5417Af564e4bFDA1c483642db72007871397896"
    # weth = "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619"
    # pair_address = get_pair("0x29bf8Df7c9a005a080E4599389Bf11f15f6afA6A", "0xc2132d05d31c914a87c6611c10748aeb04b58e8f")
    # print(f"pair_address: {pair_address}")
    # rate_limit_lua_script_shas = dict()
    # loop = asyncio.get_event_loop()
    # data = loop.run_until_complete(
    #     get_pair_contract_trades_async(loop, rate_limit_lua_script_shas, '0x9fae36a18ef8ac2b43186ade5e2b07403dc742b1', 14841443, 14841463)
    # )

    # loop = asyncio.get_event_loop()
    # rate_limit_lua_script_shas = dict()
    # data = loop.run_until_complete(
    #     get_liquidity_of_each_token_reserve_async(loop, rate_limit_lua_script_shas, '0xdf42388059692150d0a9de836e4171c7b9c09cbf')
    # )

    # print(f"\n\n{data}\n")
    pass
