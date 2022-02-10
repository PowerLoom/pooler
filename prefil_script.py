
from functools import partial
from web3 import Web3
import asyncio
import aiohttp
from redis_conn import provide_async_redis_conn_insta
from dynaconf import settings
import logging.config
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
from urllib.parse import urlencode, urljoin
from data_models import liquidityProcessedData
from decimal import Decimal

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
        logger.debug(f"Reading {file_path} file")
        json_data = json.loads(f_.read())
    return json_data


pair_contract_abi = read_json_file(f"abis/UniswapV2Pair.json")
erc20_abi = read_json_file('abis/IERC20.json')
router_contract_abi = read_json_file(f"abis/UniswapV2Router.json")

#TODO: put this in settings.json
router_addr = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff" 
dai = "0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063"

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


# initiate all contracts
try:
    # instantiate UniswapV2Factory contract (using quick swap v2 factory address)
    quick_swap_uniswap_v2_factory_contract = web3.eth.contract(
        address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.QUICK_SWAP_IUNISWAP_V2_FACTORY),
        abi=read_json_file('./abis/IUniswapV2Factory.json')
    )

except Exception as e:
    quick_swap_uniswap_v2_factory_contract = None
    logger.error(e, exc_info=True)


@provide_async_redis_conn_insta
async def cache_pair_meta_data(loop: asyncio.AbstractEventLoop, block_identifier='latest', redis_conn: aioredis.Redis = None):
    try:
        #TODO: we can cache cached_pair_addresses content with expiry date
        if not os.path.exists('static/cached_pair_addresses.json'):
            return []
        f = open('static/cached_pair_addresses1.json', 'r')
        pairs = json.loads(f.read())
        
        if len(pairs) <= 0:
            return []

        for pair_contract_address in pairs:

            pair_address = Web3.toChecksumAddress(pair_contract_address)
            print(f"pair_add:{pair_contract_address}")

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
                # logger.debug("Pair Data:")
        
                # pair contract
                pair = web3.eth.contract(
                    address=pair_address, 
                    abi=pair_contract_abi
                )

                pairTokensAddresses = await redis_conn.hgetall(uniswap_pair_contract_tokens_addresses.format(pair_address))
                if False:
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

                # token0 contract
                token0 = web3.eth.contract(
                    address=Web3.toChecksumAddress(token0Addr), 
                    abi=erc20_abi
                )
                # token1 contract
                token1 = web3.eth.contract(
                    address=Web3.toChecksumAddress(token1Addr), 
                    abi=erc20_abi
                )
                token0_decimals = 0
                token1_decimals = 0
                
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
                            "token1_decimals", token1_decimals,
                            "pair_symbol", f"{token0_symbol}-{token1_symbol}",
                            "token0Addr", f"{Web3.toChecksumAddress(token0Addr)}",
                            "token1Addr", f"{Web3.toChecksumAddress(token1Addr)}",
                        )

                        print(f"pair_symbol {token0_symbol}-{token1_symbol}")
                    
            else:
                raise Exception("exhausted_api_key_rate_limit inside uniswap_functions get async liquidity reservers")
    except Exception as exc:
        logger.error("error at cache_pair_meta_data fn: %s", exc, exc_info=True)
        raise

def get_pair(token0, token1):
    token0 = web3.toChecksumAddress(token0)
    token1 = web3.toChecksumAddress(token1)
    pair = quick_swap_uniswap_v2_factory_contract.functions.getPair(token0, token1).call()
    return pair


if __name__ == '__main__':
    
    dai = "0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063"
    gns = "0xE5417Af564e4bFDA1c483642db72007871397896"
    weth = "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619"
    
    # cache pair meta data
    loop = asyncio.get_event_loop()
    reservers = loop.run_until_complete(cache_pair_meta_data(loop))
    loop.close()