from functools import partial
from tenacity import retry, AsyncRetrying, stop_after_attempt, wait_random, wait_random_exponential, retry_if_exception_type
from typing import List
from web3 import Web3
from web3.datastructures import AttributeDict
from gnosis.eth import EthereumClient
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
    uniswap_pair_contract_V2_pair_data, uniswap_pair_cached_block_height_token_price,uniswap_eth_usd_price_zset,
    uniswap_tokens_pair_map
)
from helper_functions import (
    acquire_threading_semaphore
)

ethereum_client = EthereumClient(settings.RPC.MATIC[0])
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
factory_contract_abi = read_json_file(f"abis/IUniswapV2Factory.json")

router_addr = settings.CONTRACT_ADDRESSES.IUNISWAP_V2_ROUTER
dai = settings.CONTRACT_ADDRESSES.DAI
usdt = settings.CONTRACT_ADDRESSES.USDT
weth = settings.CONTRACT_ADDRESSES.WETH

dai_eth_contract_obj = ethereum_client.w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.DAI_WETH_PAIR),
    abi=pair_contract_abi
)
usdc_eth_contract_obj = ethereum_client.w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDC_WETH_PAIR),
    abi=pair_contract_abi
)
eth_usdt_contract_obj = ethereum_client.w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDT_WETH_PAIR),
    abi=pair_contract_abi
)
router_contract_obj = w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.IUNISWAP_V2_ROUTER),
    abi=router_contract_abi
)
factory_contract_obj = w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.IUNISWAP_V2_FACTORY),
    abi=factory_contract_abi
)

codec: ABICodec = w3.codec

UNISWAP_TRADE_EVENT_SIGS = {
    'Swap': "Swap(address,uint256,uint256,uint256,uint256,address)",
    'Mint': "Mint(address,uint256,uint256)",
    'Burn': "Burn(address,uint256,uint256,address)"
}

tokens_decimals = {
    "USDT": 6,
    "DAI": 18,
    "USDC": 6,
    "WETH": 18
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

async def check_rpc_rate_limit(redis_conn: aioredis.Redis, request_payload, error_msg, rate_limit_lua_script_shas=None, limit_incr_by=1):
    """
        rate limiter for rpc calls
    """
    if not rate_limit_lua_script_shas:
        rate_limit_lua_script_shas = await load_rate_limiter_scripts(redis_conn)
    redis_storage = AsyncRedisStorage(rate_limit_lua_script_shas, redis_conn)
    custom_limiter = AsyncFixedWindowRateLimiter(redis_storage)
    app_id = settings.RPC.MATIC[0].split('/')[-1]  # future support for loadbalancing over multiple MaticVigil RPC appID
    key_bits = [app_id, 'eth_call']  # TODO: add unique elements that can identify a request
    can_request = False
    retry_after = 1
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
            raise
        except Exception as e:
            logger.error('Caught exception on rate limiter operations: %s', e, exc_info=True)
            raise
        else:
            can_request = True

    if not can_request:
        raise RPCException(
            request=request_payload, 
            response={}, underlying_exception=None, 
            extra_info=error_msg
        )
    return can_request

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
        raise e
    else:
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
            if log.args.get('amount1Out') == 0:

                current0_swapped = log.args.get('amount0Out') / 10 ** int(pair_per_token_metadata['token0']['decimals'])
                token0_amount = current0_swapped
                token0_swapped_usd = current0_swapped * token0_price_map.get(log["blockNumber"], list(token0_price_map.values())[0])
                
                current1_swapped = log.args.get('amount1In') / 10 ** int(pair_per_token_metadata['token1']['decimals'])
                token1_amount = current1_swapped
                token1_swapped_usd = current1_swapped * token1_price_map.get(log["blockNumber"], list(token1_price_map.values())[0])
            elif log.args.get('amount0Out') == 0:
                current0_swapped = log.args.get('amount0In') / 10 ** int(pair_per_token_metadata['token0']['decimals']) 
                token0_amount = current0_swapped
                token0_swapped_usd = current0_swapped * token0_price_map.get(log["blockNumber"], list(token0_price_map.values())[0])

                current1_swapped = log.args.get('amount1Out') / 10 ** int(pair_per_token_metadata['token1']['decimals'])
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
            if token1_swapped_usd and token0_swapped_usd:
                trade_amount_usd = token1_swapped_usd if token1_swapped_usd > token0_swapped_usd else token0_swapped_usd
            else:
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
            if parsed_log_obj_values.get('amount1Out') == 0:
            
                current0_swapped = parsed_log_obj_values.get('amount0Out') / 10 ** int(pair_per_token_metadata['token0']['decimals'])
                token0_swapped += current0_swapped
                token0_swapped_usd += current0_swapped * token0_price_map.get(parsed_log_obj_values.get('blockNumber'), list(token0_price_map.values())[0])
                
                current1_swapped = parsed_log_obj_values.get('amount1In') / 10 ** int(pair_per_token_metadata['token1']['decimals'])
                token1_swapped += current1_swapped
                token1_swapped_usd += current1_swapped * token1_price_map.get(parsed_log_obj_values.get('blockNumber'), list(token1_price_map.values())[0])

            elif parsed_log_obj_values.get('amount0Out') == 0:

                current0_swapped = parsed_log_obj_values.get('amount0In') / 10 ** int(pair_per_token_metadata['token0']['decimals']) 
                token0_swapped += current0_swapped
                token0_swapped_usd += current0_swapped * token0_price_map.get(parsed_log_obj_values.get('blockNumber'), list(token0_price_map.values())[0])

                current1_swapped = parsed_log_obj_values.get('amount1Out') / 10 ** int(pair_per_token_metadata['token1']['decimals'])
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
        if token1_swapped_usd and token0_swapped_usd:
            trade_volume_usd = token1_swapped_usd if token1_swapped_usd > token0_swapped_usd else token0_swapped_usd
        else:
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


def get_maker_pair_data(prop):
    prop = prop.lower()
    if prop.lower() == "name":
        return "Maker"
    elif prop.lower() == "symbol":
        return "MKR"
    else:
        return "Maker"

async def get_pair_per_token_metadata(
    pair_address,
    loop: asyncio.AbstractEventLoop,
    redis_conn: aioredis.Redis,
    rate_limit_lua_script_shas
):
    """
        returns information on the tokens contained within a pair contract - name, symbol, decimals of token0 and token1
        also returns pair symbol by concatenating {token0Symbol}-{token1Symbol}
    """
    try:
        pair_address = Web3.toChecksumAddress(pair_address)

        # check if cache exist
        pair_token_addresses_cache, pair_tokens_data_cache = await asyncio.gather(
            redis_conn.hgetall(uniswap_pair_contract_tokens_addresses.format(pair_address)),
            redis_conn.hgetall(uniswap_pair_contract_tokens_data.format(pair_address))
        )

        # parse addresses cache or call eth rpc
        token0Addr = None
        token1Addr = None
        if pair_token_addresses_cache:
            token0Addr = Web3.toChecksumAddress(pair_token_addresses_cache[b"token0Addr"].decode('utf-8'))
            token1Addr = Web3.toChecksumAddress(pair_token_addresses_cache[b"token1Addr"].decode('utf-8'))
        else:
            pair_contract_obj = w3.eth.contract(
                address=Web3.toChecksumAddress(pair_address),
                abi=pair_contract_abi
            )
            await check_rpc_rate_limit(
                redis_conn=redis_conn, request_payload={"pair_address": pair_address},
                error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get_pair_metadata fn"},
                rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1
            )
            token0Addr, token1Addr = ethereum_client.batch_call([
                pair_contract_obj.functions.token0(),
                pair_contract_obj.functions.token1()
            ])

            await redis_conn.hset(
                name=uniswap_pair_contract_tokens_addresses.format(pair_address),
                mapping={
                    'token0Addr': token0Addr,
                    'token1Addr': token1Addr
                }
            )

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

        # parse token data cache or call eth rpc
        if pair_tokens_data_cache:
            token0_decimals = pair_tokens_data_cache[b"token0_decimals"].decode('utf-8')
            token1_decimals = pair_tokens_data_cache[b"token1_decimals"].decode('utf-8')
            token0_symbol = pair_tokens_data_cache[b"token0_symbol"].decode('utf-8')
            token1_symbol = pair_tokens_data_cache[b"token1_symbol"].decode('utf-8')
            token0_name = pair_tokens_data_cache[b"token0_name"].decode('utf-8')
            token1_name = pair_tokens_data_cache[b"token1_name"].decode('utf-8')
        else:
            tasks = list()
            
            #special case to handle maker token
            maker_token0 = None
            maker_token1 = None
            if(Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.MAKER) == Web3.toChecksumAddress(token0Addr)):
                token0_name = get_maker_pair_data('name')
                token0_symbol = get_maker_pair_data('symbol')
                maker_token0 = True
            else:
                tasks.append(token0.functions.name())
                tasks.append(token0.functions.symbol())
            tasks.append(token0.functions.decimals())


            if(Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.MAKER) == Web3.toChecksumAddress(token1Addr)):
                token1_name = get_maker_pair_data('name')
                token1_symbol = get_maker_pair_data('symbol')
                maker_token1 = True
            else:
                tasks.append(token1.functions.name())
                tasks.append(token1.functions.symbol())
            tasks.append(token1.functions.decimals())

            await check_rpc_rate_limit(
                redis_conn=redis_conn, request_payload={"pair_address": pair_address},
                error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get_pair_metadata fn"},
                rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1
            )
            if maker_token1:
                [token0_name, token0_symbol, token0_decimals, token1_decimals] = ethereum_client.batch_call(
                    tasks
                )
            elif maker_token0:
                [token0_decimals, token1_name, token1_symbol, token1_decimals] = ethereum_client.batch_call(
                    tasks
                )
            else:
                [
                    token0_name, token0_symbol, token0_decimals, token1_name, token1_symbol, token1_decimals
                ] = ethereum_client.batch_call(tasks)
            
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
    except Exception as err:
        # this will be retried in next cycle
        logger.error(f"RPC error while fetcing metadata for pair {pair_address}, error_msg:{err}", exc_info=True)
        raise err

async def get_eth_price_usd(block_height, loop: asyncio.AbstractEventLoop, redis_conn: aioredis.Redis, rate_limit_lua_script_shas):
    """
        returns the price of eth in usd at a given block height
    """

    try:
        eth_price_usd = 0
        
        if block_height != 'latest':
            cached_price = await redis_conn.zrangebyscore(
                name=uniswap_eth_usd_price_zset,
                min=int(block_height),
                max=int(block_height)
            )
            cached_price = cached_price[0].decode('utf-8') if len(cached_price) > 0 else False
            if cached_price:
                cached_price = json.loads(cached_price)
                eth_price_usd = cached_price['price']
                return eth_price_usd

        # we are making single batch call here:
        await check_rpc_rate_limit(
            redis_conn=redis_conn, request_payload={"block_identifier": block_height},
            error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get eth usd price fn"},
            rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1
        )
        [dai_eth_pair_reserves, usdc_eth_pair_reserves, eth_usdt_pair_reserves] = ethereum_client.batch_call([
            dai_eth_contract_obj.functions.getReserves(),
            usdc_eth_contract_obj.functions.getReserves(),
            eth_usdt_contract_obj.functions.getReserves()
        ],block_identifier=block_height)

        dai_eth_pair_eth_reserve = dai_eth_pair_reserves[1]/10**tokens_decimals["WETH"]
        dai_eth_pair_dai_reserve = dai_eth_pair_reserves[0]/10**tokens_decimals["DAI"]
        dai_price = dai_eth_pair_dai_reserve / dai_eth_pair_eth_reserve

        usdc_eth_pair_eth_reserve = usdc_eth_pair_reserves[1]/10**tokens_decimals["WETH"]
        usdc_eth_pair_usdc_reserve = usdc_eth_pair_reserves[0]/10**tokens_decimals["USDC"]
        usdc_price = usdc_eth_pair_usdc_reserve / usdc_eth_pair_eth_reserve

        usdt_eth_pair_eth_reserve = eth_usdt_pair_reserves[0]/10**tokens_decimals["WETH"]
        usdt_eth_pair_usdt_reserve = eth_usdt_pair_reserves[1]/10**tokens_decimals["USDT"]
        usdt_price = usdt_eth_pair_usdt_reserve / usdt_eth_pair_eth_reserve
        
        total_eth_liquidity = dai_eth_pair_eth_reserve + usdc_eth_pair_eth_reserve + usdt_eth_pair_eth_reserve

        daiWeight = dai_eth_pair_eth_reserve / total_eth_liquidity
        usdcWeight = usdc_eth_pair_eth_reserve / total_eth_liquidity
        usdtWeight = usdt_eth_pair_eth_reserve / total_eth_liquidity

        eth_price_usd = daiWeight * dai_price + usdcWeight * usdc_price + usdtWeight * usdt_price

        # cache price at height
        if block_height != 'latest':
            await asyncio.gather(
                redis_conn.zadd(
                    name=uniswap_eth_usd_price_zset,
                    mapping={json.dumps({
                        'blockHeight': block_height,
                        'price': eth_price_usd
                    }): int(block_height)}
                ),
                redis_conn.zremrangebyscore(
                    name=uniswap_eth_usd_price_zset,
                    min=0,
                    max= block_height - int(settings.NUMBER_OF_BLOCKS_IN_EPOCH) * int(settings.PRUNE_PRICE_ZSET_EPOCH_MULTIPLIER)
                )
            )

    except Exception as err:
        logger.error(f"RPC ERROR failed to fetch ETH price, error_msg:{err}")
        raise err
    else:
        return float(eth_price_usd)

async def get_white_token_data(
    pair_contract_obj, 
    pair_metadata, 
    white_token, 
    target_token, 
    block_height, 
    loop: asyncio.AbstractEventLoop, redis_conn,
    rate_limit_lua_script_shas
):
    token_price = 0
    white_token_reserves = 0
    white_token = Web3.toChecksumAddress(white_token)
    target_token = Web3.toChecksumAddress(target_token)
    white_token_metadata = pair_metadata["token0"] if white_token == pair_metadata["token0"]["address"] else pair_metadata["token1"]
    token_eth_price = 0
    tasks = list()
    try:

        #find price of white token in terms of target token
        tasks.append(pair_contract_obj.functions.getReserves())


        await check_rpc_rate_limit(
            redis_conn=redis_conn, request_payload={"token_contract": target_token},
            error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get_white_token_data fn"},
            rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1
        )
        if Web3.toChecksumAddress(white_token) == Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH):
            # set derived eth as 1 if token is weth
            token_eth_price = 1
            
            [pair_reserve] = ethereum_client.batch_call(
                tasks, block_identifier=block_height
            )
        else:
            tasks.append(router_contract_obj.functions.getAmountsOut(
                10 ** int(white_token_metadata['decimals']), 
                [
                    Web3.toChecksumAddress(white_token_metadata['address']),
                    Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH)
                ]
            ))
            
            [pair_reserve, token_eth_price] = ethereum_client.batch_call(
                tasks, block_identifier=block_height
            )
            
            if token_eth_price:
                token_eth_price = token_eth_price[1]/10**tokens_decimals["WETH"] if token_eth_price[1] !=0 else 0
            else:
                token_eth_price = 0

            

        if not pair_reserve:
            return token_price, white_token_reserves, float(token_eth_price)

        pair_reserve_token0 = pair_reserve[0]/10**int(pair_metadata['token0']["decimals"])
        pair_reserve_token1 = pair_reserve[1]/10**int(pair_metadata['token1']["decimals"])

        if pair_reserve_token0 == 0 or pair_reserve_token1 == 0:
            return token_price, white_token_reserves, float(token_eth_price)

        if Web3.toChecksumAddress(pair_metadata['token0']["address"]) == white_token:
            token_price = float(pair_reserve_token0 / pair_reserve_token1)
            white_token_reserves = pair_reserve_token0
        else:
            token_price = float(pair_reserve_token1 / pair_reserve_token0)
            white_token_reserves = pair_reserve_token1

        return token_price, white_token_reserves, float(token_eth_price)


    except Exception as error:
        logger.error(f"Error: failed to get whitelisted token data, error_msg:{str(error)}")
        raise error


async def pair_based_token_price(pair_contract_obj, pair_metadata, white_token, target_token, block_height, loop: asyncio.AbstractEventLoop, redis_conn):
    token_price = 0
    white_token = Web3.toChecksumAddress(white_token)
    target_token = Web3.toChecksumAddress(target_token)

    #find price of white token in terms of target token
    pair_reserve_func = partial(pair_contract_obj.functions.getReserves().call, block_identifier=block_height)

    pair_reserve = await loop.run_in_executor(func=pair_reserve_func, executor=None)

    if not pair_reserve:
        return token_price


    pair_reserve_token0 = pair_reserve[0]/10**int(pair_metadata['token0']["decimals"])
    pair_reserve_token1 = pair_reserve[1]/10**int(pair_metadata['token1']["decimals"])

    if Web3.toChecksumAddress(pair_metadata['token0']["address"]) == white_token:
        token_price = float(pair_reserve_token0 / pair_reserve_token1)
    else:
        token_price = float(pair_reserve_token1 / pair_reserve_token0)

    return token_price

async def get_derived_eth_per_token(contract_obj, token_metadata, block_height, loop):
    token_eth_price = 0
    try:
        if Web3.toChecksumAddress(token_metadata['address']) == Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH):
            token_eth_price = 1
        else:
            priceFunction_token0 = partial(contract_obj.functions.getAmountsOut(
                10 ** int(token_metadata['decimals']), 
                [
                    Web3.toChecksumAddress(token_metadata['address']),
                    Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH)
                ]
            ).call, block_identifier=block_height)
            token_eth_price = await loop.run_in_executor(func=priceFunction_token0, executor=None)
            if token_eth_price:
                token_eth_price = token_eth_price[1]/10**tokens_decimals["WETH"] if token_eth_price[1] !=0 else 0
            else:
                token_eth_price = 0
    except Exception as error:
        logger.error(f"Error: failed to derived eth per token, error_msg:{str(error)}")
        token_eth_price = 0
        raise error
    else:
        return float(token_eth_price)

def return_last_price_value(retry_state):
        """After max retry attempt, return the last price value for token"""

        try:
            retry_state.outcome.result()
        except Exception as err:
            logger.error(f"Error: token price exception after max retries: {str(err)}, setting price to 0")
        else:
            logger.debug(f"Error: there is some unknown issue in token price rpc call, setting price to 0")

        return 0

@retry(
    reraise=True,
    retry=retry_if_exception_type(RPCException), 
    wait=wait_random_exponential(multiplier=1, max=10), 
    stop=stop_after_attempt(settings.UNISWAP_FUNCTIONS.RETRIAL_ATTEMPTS)
)
async def get_token_price_at_block_height(
    token_metadata, block_height, 
    loop: asyncio.AbstractEventLoop, 
    redis_conn: aioredis.Redis, 
    rate_limit_lua_script_shas=None, 
    debug_log=True
):
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

        if Web3.toChecksumAddress(token_metadata['address']) == Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH):
            token_price = await get_eth_price_usd(block_height, loop, redis_conn, rate_limit_lua_script_shas)
        else:
            token_eth_price = 0

            for white_token in settings.UNISWAP_V2_WHITELIST:
                white_token = Web3.toChecksumAddress(white_token)
                pairAddress = await get_pair(factory_contract_obj, white_token, token_metadata['address'], loop, redis_conn, rate_limit_lua_script_shas)
                if pairAddress != "0x0000000000000000000000000000000000000000": 
                    pair_contract_obj = w3.eth.contract(
                        address=Web3.toChecksumAddress(pairAddress),
                        abi=pair_contract_abi
                    )
                    new_pair_metadata = await get_pair_per_token_metadata(
                        pair_address=pairAddress,
                        loop=loop,
                        redis_conn=redis_conn,
                        rate_limit_lua_script_shas=rate_limit_lua_script_shas
                    )


                    white_token_price, white_token_reserves, white_token_derived_eth = await get_white_token_data(
                        pair_contract_obj, new_pair_metadata, white_token, 
                        token_metadata['address'], block_height, loop, redis_conn, rate_limit_lua_script_shas
                    )

                    # ignore if reservers are less than threshold
                    white_token_reserves = white_token_reserves * white_token_derived_eth
                    if white_token_reserves < 2:
                        continue

                    token_eth_price = white_token_price * white_token_derived_eth
                    break
                        
            
            if token_eth_price != 0:
                eth_usd_price = await get_eth_price_usd(block_height, loop, redis_conn, rate_limit_lua_script_shas)
                token_price = token_eth_price * eth_usd_price 
            
            if debug_log:
                logger.debug(f"{token_metadata['symbol']}: price is {token_price} | its eth price is {token_eth_price}")
            
        # cache price at height
        if block_height != 'latest':
            await redis_conn.zadd(
                name=uniswap_pair_cached_block_height_token_price.format(Web3.toChecksumAddress(token_metadata['address'])),
                mapping={json.dumps({
                    'blockHeight': block_height,
                    'price': token_price
                }): int(block_height)} # timestamp so zset do not ignore same height on multiple heights
            )
        
        return token_price

    except Exception as err:
        raise RPCException(request={"contract": token_metadata['address'], "block_identifier": block_height}, 
            response={}, underlying_exception=None, 
            extra_info={'msg': f"rpc error: {str(err)}"}) from err





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

        if fetch_timestamp:
            block_det_func = partial(w3.eth.get_block, block_identifier)
            try:
                await check_rpc_rate_limit(
                    redis_conn=redis_conn, request_payload={"contract": pair_address, "block_identifier": block_identifier},
                    error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get async liquidity reserves"},
                    rate_limit_lua_script_shas=rate_limit_lua_script_shas
                )
                block_details = await loop.run_in_executor(func=block_det_func, executor=None)
            except Exception as err:
                logger.error('Error attempting to get block details of block_identifier %s: %s, retrying again', block_identifier, err, exc_info=True)
                raise err
        else:
            block_details = None
        
        pair_per_token_metadata = await get_pair_per_token_metadata(
            pair_address=pair_address,
            loop=loop,
            redis_conn=redis_conn,
            rate_limit_lua_script_shas=rate_limit_lua_script_shas
        )
        

        pfunc_get_reserves = partial(pair.functions.getReserves().call, block_identifier=block_identifier)
        async for attempt in AsyncRetrying(reraise=True, stop=stop_after_attempt(3), wait=wait_random(1, 2)):
            with attempt:
                executor_gather = list()
                executor_gather.append(loop.run_in_executor(func=pfunc_get_reserves, executor=None))
                executor_gather.append(get_token_price_at_block_height(pair_per_token_metadata['token0'], block_identifier, loop, redis_conn, rate_limit_lua_script_shas))
                executor_gather.append(get_token_price_at_block_height(pair_per_token_metadata['token1'], block_identifier, loop, redis_conn, rate_limit_lua_script_shas))

                # get token price function takes care of its own rate limit
                await check_rpc_rate_limit(
                    redis_conn=redis_conn, request_payload={"contract": pair_address, "block_identifier": block_identifier},
                    error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get async liquidity reserves"},
                    rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1
                )
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
    except Exception as exc:
        logger.error("error at async_get_liquidity_of_each_token_reserve fn, retrying..., error_msg: %s", exc, exc_info=True)
        raise RPCException(request={"contract": pair_address, "block_height": block_identifier}, 
            response={}, underlying_exception=None, 
            extra_info={'msg': f"Error: async_get_liquidity_of_each_token_reserve error_msg: {str(exc)}"}) from exc


async def get_trade_volume_epoch_price_map(
        loop,
        rate_limit_lua_script_shas: dict,
        to_block, from_block,
        token_metadata,
        redis_conn: aioredis.Redis,
        debug_log=False
):  
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

        try:
            async for attempt in AsyncRetrying(reraise=True, stop=stop_after_attempt(3), wait=wait_random(1, 5)):
                with attempt:
                    price = await get_token_price_at_block_height(token_metadata, block, loop, redis_conn, rate_limit_lua_script_shas, debug_log)
                    price_map[block] = price
                    if price:
                        break
        except Exception as err:
            # pair_contract price can't retrieved, this is mostly with sepcific coins log it and fetch price for newer ones
            logger.error(f"Failed to fetch token price | error_msg: {str(err)} | epoch: {to_block}-{from_block}", exc_info=True)
            raise err
    
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

        if fetch_timestamp:
            block_det_func = partial(w3.eth.get_block, to_block)
            try:
                await check_rpc_rate_limit(
                    redis_conn=redis_conn, request_payload={"contract": pair_address, "to_block": to_block, "from_block": from_block},
                    error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get async trade volume"},
                    rate_limit_lua_script_shas=rate_limit_lua_script_shas
                )
                block_details = await ev_loop.run_in_executor(func=block_det_func, executor=None)
            except Exception as err:
                logger.error('Error attempting to get block details of to_block %s: %s, retrying again', to_block, err, exc_info=True)
                raise err
        else:
            block_details = None

        pair_per_token_metadata = await get_pair_per_token_metadata(
            pair_address=pair_address,
            loop=ev_loop,
            redis_conn=redis_conn,
            rate_limit_lua_script_shas=rate_limit_lua_script_shas
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
        
        await check_rpc_rate_limit(
            redis_conn=redis_conn, request_payload={"contract": pair_address, "to_block": to_block, "from_block": from_block},
            error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get async trade volume"},
            rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=3
        )
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

        # raise RPCException(request={"contract": pair_address, "fromBlock": from_block, "toBlock": to_block}, 
        # response={}, underlying_exception=None, 
        # extra_info={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get async trade volume"})
    except Exception as exc:
        logger.error("error at get_pair_contract_trades_async fn: %s", exc, exc_info=True)
        raise RPCException(request={"contract": pair_address, "fromBlock": from_block, "toBlock": to_block}, 
            response={}, underlying_exception=None, 
            extra_info={'msg': f"error: get_pair_contract_trades_async, error_msg: {str(exc)}"}) from exc


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


async def get_pair(
    factory_contract_obj, 
    token0, token1, 
    loop: asyncio.AbstractEventLoop, 
    redis_conn: aioredis.Redis, 
    rate_limit_lua_script_shas
):

    #check if pair cache exists
    pair_address_cache = await redis_conn.hget(
        uniswap_tokens_pair_map, 
        f"{Web3.toChecksumAddress(token0)}-{Web3.toChecksumAddress(token1)}"
    ) 
    if pair_address_cache:
        pair_address_cache = pair_address_cache.decode('utf-8')
        return Web3.toChecksumAddress(pair_address_cache)

    # get pair from eth rpc 
    pair_func = partial(factory_contract_obj.functions.getPair(
        Web3.toChecksumAddress(token0), 
        Web3.toChecksumAddress(token1)
    ).call)
    await check_rpc_rate_limit(
        redis_conn=redis_conn, request_payload={"token0": token0, "token1": token1},
        error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get_pair fn"},
        rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1
    )
    pair = await loop.run_in_executor(func=pair_func, executor=None)
    
    # cache the pair address
    await redis_conn.hset(
        name=uniswap_tokens_pair_map,
        mapping={f"{Web3.toChecksumAddress(token0)}-{Web3.toChecksumAddress(token1)}": Web3.toChecksumAddress(pair)}
    )
    
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
    #     get_pair_contract_trades_async(loop, rate_limit_lua_script_shas, '0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc', 15140843, 15140863)
    # )

    # loop = asyncio.get_event_loop()
    # rate_limit_lua_script_shas = dict()
    # data = loop.run_until_complete(
    #     get_liquidity_of_each_token_reserve_async(loop, rate_limit_lua_script_shas, '0xec54859519293b8784bc5bf28144166f313618af')
    # )

    # print(f"\n\n{data}\n")
    pass
