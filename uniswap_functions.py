from functools import partial
from web3 import Web3
import asyncio
import aiohttp
from redis_conn import provide_async_redis_conn_insta
from dynaconf import settings
import logging.config
from proto_system_logging import config_logger_with_namespace
import os
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
    uniswap_pair_contract_tokens_addresses, uniswap_pair_contract_tokens_data
)
from helper_functions import (
    acquire_threading_semaphore
)
from tenacity import Retrying, stop_after_attempt, wait_random_exponential

web3 = Web3(Web3.HTTPProvider(settings.RPC.MATIC[0]))
# TODO: Use async http provider once it is considered stable by the web3.py project maintainers
# web3_async = Web3(Web3.AsyncHTTPProvider(settings.RPC.MATIC[0]))

logger = logging.getLogger('PowerLoom|UniswapHelpers')
logger.setLevel(logging.DEBUG)
logger.handlers = [logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]


# Initialize rate limits when program starts
GLOBAL_RPC_RATE_LIMIT_STR = settings.RPC.rate_limit
PARSED_LIMITS = limit_parse_many(GLOBAL_RPC_RATE_LIMIT_STR)


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
    LUA_SCRIPT_SHAS = {
        "script_incr_expire": script_incr_expire,
        "script_clear_keys": script_clear_keys_sha
    }
    return LUA_SCRIPT_SHAS


def read_json_file(file_path: str):
    """Read given json file and return its content as a dictionary."""
    try:
        f_ = open(file_path, 'r')
    except Exception as e:
        logger.warning(f"Unable to open the {file_path} file")
        logger.error(e, exc_info=True)
        raise e
    else:
        logger.debug(f"Reading {file_path} file")
        json_data = json.loads(f_.read())
    return json_data


# initiate all contracts
try:
    # instantiate UniswapV2Factory contract (using quick swap v2 factory address)
    quick_swap_uniswap_v2_factory_contract = web3.eth.contract(
        address=settings.CONTRACT_ADDRESSES.QUICK_SWAP_IUNISWAP_V2_FACTORY,
        abi=read_json_file('./abis/IUniswapV2Factory.json')
    )

    # instantiate UniswapV2Pair contract (using quick swap v2 pair address)
    quick_swap_uniswap_v2_pair_contract = web3.eth.contract(
        address=settings.CONTRACT_ADDRESSES.QUICK_SWAP_IUNISWAP_V2_PAIR,
        abi=read_json_file('./abis/UniswapV2Pair.json')
    )

except Exception as e:
    quick_swap_uniswap_v2_factory_contract = None
    quick_swap_uniswap_v2_pair_contract = None
    logger.error(e, exc_info=True)


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

        with open('static/cached_pair_addresses.json', 'w') as f:
            json.dump(all_pairs, f)
        return all_pairs
    except Exception as e:
        logger.error(e, exc_info=True)
        raise e

# asynchronously get liquidity of each token reserve
@provide_async_redis_conn_insta
async def async_get_liquidity_of_each_token_reserve(loop: asyncio.AbstractEventLoop, pair_address, block_identifier='latest', redis_conn: aioredis.Redis = None):
    try:
        redis_storage = AsyncRedisStorage(await load_rate_limiter_scripts(redis_conn), redis_conn)
        custom_limiter = AsyncFixedWindowRateLimiter(redis_storage)
        limit_incr_by = 1   # score to be incremented for each request
        app_id = settings.RPC.MATIC[0].split('/')[-1]  # future support for loadbalancing over multiple MaticVigil RPC appID
        key_bits = [app_id, 'eth_getLogs']  # TODO: add unique elements that can identify a request
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
                    retry_after = (datetime.now() + timedelta(0,retry_after)).isoformat()
                    can_request = False
                    break  # make sure to break once false condition is hit
            except (
                    aioredis.errors.ConnectionClosedError, aioredis.errors.ConnectionForcedCloseError,
                    aioredis.errors.PoolClosedError
            ) as e:
                # shit can happen while each limit check call hits Redis, handle appropriately
                logger.debug('Bypassing rate limit check for appID because of Redis exception: ' + str({'appID': app_id, 'exception': e}))
            else:
                can_request = True
        if can_request:
            logger.debug("Pair Data:")
    
            # pair contract
            pair = web3.eth.contract(
                address=pair_address, 
                abi=read_json_file(f"abis/UniswapV2Pair.json")
            )

            pairTokensAddresses = await redis_conn.hgetall(uniswap_pair_contract_tokens_addresses.format(pair_address))
            if pairTokensAddresses:
                token0Addr = pairTokensAddresses[b"token0Addr"].decode('utf-8')
                token1Addr = pairTokensAddresses[b"token1Addr"].decode('utf-8')
            else:
                # run in loop's default executor
                pfunc_0 = partial(pair.functions.token0().call)
                token0Addr = await loop.run_in_executor(func=pfunc_0, executor=None)
                pfunc_1 = partial(pair.functions.token1().call)
                token1Addr = await loop.run_in_executor(func=pfunc_1, executor=None)
                await redis_conn.hmset(uniswap_pair_contract_tokens_addresses.format(pair_address), 'token0Addr', token0Addr, 'token1Addr', token1Addr)
            
            # introduce block height in get reserves
            pfunc_get_reserves = partial(pair.functions.getReserves().call, {'block_identifier': block_identifier})
            reserves = await loop.run_in_executor(func=pfunc_get_reserves, executor=None)
            logger.debug(f"Token0: {token0Addr}, Reserves: {reserves[0]}")
            logger.debug(f"Token1: {token1Addr}, Reserves: {reserves[1]}")

            # token0 contract
            token0 = web3.eth.contract(
                address=token0Addr, 
                abi=read_json_file('abis/IERC20.json')
            )
            # token1 contract
            token1 = web3.eth.contract(
                address=token1Addr, 
                abi=read_json_file('abis/IERC20.json')
            )

            pairTokensData = await redis_conn.hgetall(uniswap_pair_contract_tokens_data.format(pair_address))
            if pairTokensData:
                token1_decimals = pairTokensData[b"token0_decimals"].decode('utf-8')
                token0_decimals = pairTokensData[b"token1_decimals"].decode('utf-8')
            else:
                executor_gather = list()
            
                for attempt in Retrying(reraise=True, wait=wait_random_exponential(multiplier=1, min=10, max=60), stop=stop_after_attempt(settings.UNISWAP_FUNCTIONS.RETRIAL_ATTEMPTS)):
                    with attempt:
                        executor_gather.append(loop.run_in_executor(func=token0.functions.name().call, executor=None))
                        executor_gather.append(loop.run_in_executor(func=token0.functions.symbol().call, executor=None))
                        executor_gather.append(loop.run_in_executor(func=token0.functions.decimals().call, executor=None))

                        executor_gather.append(loop.run_in_executor(func=token1.functions.name().call, executor=None))
                        executor_gather.append(loop.run_in_executor(func=token1.functions.symbol().call, executor=None))
                        executor_gather.append(loop.run_in_executor(func=token1.functions.decimals().call, executor=None))

                        [
                            token0_name, token0_symbol, token0_decimals,
                            token1_name, token1_symbol, token1_decimals
                        ] = await asyncio.gather(*executor_gather)

                        await redis_conn.hmset(
                            uniswap_pair_contract_tokens_data.format(pair_address), 
                            "token0_name", token0_name,
                            "token0_symbol", token0_symbol,
                            "token0_decimals", token0_decimals,
                            "token1_name", token1_name,
                            "token1_symbol", token1_symbol,
                            "token1_decimals", token1_decimals
                        )

            logger.debug(f"Decimals of token1: {token1_decimals}, Decimals of token1: {token0_decimals}")
            logger.debug(f"reserves[0]/10**token0_decimals: {reserves[0]/10**int(token0_decimals)}, reserves[1]/10**token1_decimals: {reserves[1]/10**int(token1_decimals)}")
            return {"token0": reserves[0]/10**int(token0_decimals), "token1": reserves[1]/10**int(token1_decimals)}
        else:
            raise Exception("exhausted_api_key_rate_limit inside uniswap_functions get async liquidity reservers")
    except Exception as exc:
        logger.error("error at async_get_liquidity_of_each_token_reserve fn: %s", exc, exc_info=True)
        raise


# get liquidity of each token reserve
def get_liquidity_of_each_token_reserve(pair_address, block_identifier='latest'):
    logger.debug("Pair Data:")
    
    #pair contract
    pair = web3.eth.contract(
        address=pair_address, 
        abi=read_json_file(f"abis/UniswapV2Pair.json")
    )

    token0Addr = pair.functions.token0().call()
    token1Addr = pair.functions.token1().call()
    # async limits rate limit check
    # if rate limit checks out then we call
    # introduce block height in get reserves
    reservers = pair.functions.getReserves().call(block_identifier=block_identifier)
    logger.debug(f"Token0: {token0Addr}, Reservers: {reservers[0]}")
    logger.debug(f"Token1: {token1Addr}, Reservers: {reservers[1]}")
    

    #toke0 contract
    token0 = web3.eth.contract(
        address=token0Addr, 
        abi=read_json_file('abis/IERC20.json')
    )
    #toke1 contract
    token1 = web3.eth.contract(
        address=token1Addr, 
        abi=read_json_file('abis/IERC20.json')
    )

    token0_decimals = token0.functions.decimals().call()
    token1_decimals = token1.functions.decimals().call()

    
    logger.debug(f"Decimals of token1: {token1_decimals}, Decimals of token1: {token0_decimals}")
    logger.debug(f"reservers[0]/10**token0_decimals: {reservers[0]/10**token0_decimals}, reservers[1]/10**token1_decimals: {reservers[1]/10**token1_decimals}")

    return {"token0": reservers[0]/10**token0_decimals, "token1": reservers[1]/10**token1_decimals}

def get_pair(token0, token1):
    pair = quick_swap_uniswap_v2_factory_contract.functions.getPair(token0, token1).call()
    return pair
    


if __name__ == '__main__':
    
    #here instead of calling get pair we can directly use cached all pair addresses
    dai= "0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063"
    gns= "0xE5417Af564e4bFDA1c483642db72007871397896"
    pair_address = get_pair(dai, gns)
    logger.debug(f"Pair address : {pair_address}")
    logger.debug(get_liquidity_of_each_token_reserve(pair_address))

    # #we can pass block_identifier=chain_height
    # print(get_liquidity_of_each_token_reserve(pair_address, block_identifier=24265790))

    # async liqudity function
    loop = asyncio.get_event_loop()
    reservers = loop.run_until_complete(async_get_liquidity_of_each_token_reserve(loop, pair_address=pair_address))
    loop.close()
