from uniswap_functions import (
    get_pair_per_token_metadata, SCRIPT_CLEAR_KEYS, SCRIPT_SET_EXPIRE, SCRIPT_INCR_EXPIRE, GLOBAL_RPC_RATE_LIMIT_STR,
    load_rate_limiter_scripts, PARSED_LIMITS, pair_contract_abi, get_all_pairs, get_pair, read_json_file
)
from functools import partial
from web3 import Web3
from async_limits.strategies import AsyncFixedWindowRateLimiter
from async_limits.storage import AsyncRedisStorage
from async_limits import parse_many as limit_parse_many
from redis_conn import provide_async_redis_conn_insta
from tenacity import Retrying, wait_random_exponential, stop_after_attempt
import aioredis
import time
from datetime import datetime, timedelta
from dynaconf import settings
import asyncio
import aiohttp
import web3
import asyncio
import logging
import json
import os
import sys


""" Inititalize the logger """
retrieval_logger = logging.getLogger('PowerLoom|EthLogs|worker')
retrieval_logger.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(levelname)-8s %(name)-4s %(asctime)s %(msecs)d %(module)s-%(funcName)s: %(message)s")
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(formatter)
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.ERROR)
retrieval_logger.handlers = [
    logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT),
    stdout_handler, stderr_handler
]

if os.path.exists('static/cached_pair_addresses.json'):
    f = open('static/cached_pair_addresses.json', 'r')
    CACHED_PAIR_CONTRACTS = json.loads(f.read())
else:
    CACHED_PAIR_CONTRACTS = list()


@provide_async_redis_conn_insta
async def cache_pair_meta_data(redis_conn: aioredis.Redis = None):
    try:
        # TODO: we can cache cached_pair_addresses content with expiry date

        if len(CACHED_PAIR_CONTRACTS) <= 0:
            return []

        for pair_contract_address in CACHED_PAIR_CONTRACTS:

            pair_address = Web3.toChecksumAddress(pair_contract_address)
            print(f"pair_add:{pair_contract_address}")

            redis_storage = AsyncRedisStorage(await load_rate_limiter_scripts(redis_conn), redis_conn)
            custom_limiter = AsyncFixedWindowRateLimiter(redis_storage)
            limit_incr_by = 1  # score to be incremented for each request
            app_id = settings.RPC.MATIC[0].split('/')[
                -1]  # future support for loadbalancing over multiple MaticVigil RPC appID
            key_bits = [app_id, 'eth_getLogs']  # TODO: add unique elements that can identify a request
            can_request = False
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
                        aioredis.errors.ConnectionClosedError, aioredis.errors.ConnectionForcedCloseError,
                        aioredis.errors.PoolClosedError
                ) as e:
                    # shit can happen while each limit check call hits Redis, handle appropriately
                    retrieval_logger.debug('Bypassing rate limit check for appID because of Redis exception: ' + str(
                        {'appID': app_id, 'exception': e}))
                else:
                    can_request = True
            if can_request:
                try:
                    # pair contract
                    pair = web3.eth.contract(
                        address=pair_address,
                        abi=pair_contract_abi
                    )
                    await get_pair_per_token_metadata(
                        pair_contract_obj=pair,
                        pair_address=pair_address,
                        loop=asyncio.get_running_loop()
                    )
                except Exception as e:
                    retrieval_logger.error(f"Error fetching pair contract meta data: {pair_contract_address} | message: {str(e)}", exc_info=True)
                    if(str(e)=="Could not transact with/call contract function, is contract deployed correctly and chain synced?"):
                        continue
                    elif (str(e)=="execution reverted"):
                        continue
                    else:
                        raise e
            else:
                raise Exception("exhausted_api_key_rate_limit inside uniswap_functions get async liquidity reservers")
    except Exception as exc:
        retrieval_logger.error("error at cache_pair_meta_data fn: %s", exc, exc_info=True)
        raise


@provide_async_redis_conn_insta
async def cache_pair_stablecoin_exchange_rates(redis_conn: aioredis.Redis = None):
    await cache_pair_meta_data()
    event_loop = asyncio.get_running_loop()
    all_pair_contracts = await event_loop.run_in_executor(executor=None, func=get_all_pairs)
    for each_pair_contract in all_pair_contracts:
        for attempt in Retrying(reraise=True, wait=wait_random_exponential(multiplier=1, min=10, max=60),
                                stop=stop_after_attempt(settings.UNISWAP_FUNCTIONS.RETRIAL_ATTEMPTS)):
            with attempt:
                # TODO: refactor rate limit check into something modular and easier to use
                # # # rate limit check - begin
                redis_storage = AsyncRedisStorage(await load_rate_limiter_scripts(redis_conn), redis_conn)
                custom_limiter = AsyncFixedWindowRateLimiter(redis_storage)
                limit_incr_by = 1  # score to be incremented for each request
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
                            aioredis.errors.ConnectionClosedError, aioredis.errors.ConnectionForcedCloseError,
                            aioredis.errors.PoolClosedError
                    ) as e:
                        # shit can happen while each limit check call hits Redis, handle appropriately
                        retrieval_logger.debug('Bypassing rate limit check for appID because of Redis exception: ' + str(
                            {'appID': app_id, 'exception': e}))
                    else:
                        can_request = True
                # # # rate limit check - end
                if can_request:
                    pair_contract_obj = web3.eth.contract(
                        address=each_pair_contract,
                        abi=pair_contract_abi
                    )
                    pair_per_token_metadata = await get_pair_per_token_metadata(
                        pair_contract_obj=pair_contract_obj,
                        pair_address=each_pair_contract
                    )
                    router_contract_obj = web3.eth.contract(
                        address="0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff", 
                        abi=read_json_file('./abis/UniswapV2Router.json')
                    )

                    print("Check if token aren't equal to WETH and then calculate prices")
                    # check if token1 is WETH
                    if Web3.toChecksumAddress(pair_per_token_metadata['token1']['address']) \
                        != Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH):
                        # TODO: 1. let x = getAmountsOut(in=1 unit of token0 i.e. 10**decimals, path=[each_pair_contract]) -- we do this because this function does not return floating/double points etc
                        #       2. y = getAmountsOut(in=x calculated above, path=[WETH-USDT pair contract])
                        #       3. store exchange value y/10**USDTdecimals for token0 -> US DOLLAR
                        #       4. research on 3
                        print("calculating price...")
                        #router_contract.functions.getAmountsOut(100000000000000000, [Web3.toChecksumAddress(token0Addr), Web3.toChecksumAddress(usdt)]).call()
                        loop = asyncio.get_running_loop()
                        priceFunction = partial(router_contract_obj.functions.getAmountsOut(100000000000000000, ["0x7ceb23fd6bc0add59e62ac25578270cff1b9f619", "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"]).call)
                        x = await loop.run_in_executor(func=priceFunction, executor=None)
                        #y = router_contract_obj.functions.getAmountsOut(x, [str(settings.CONTRACT_ADDRESSES.WETH-USDT)]).call()
                        print("Calculated prices")
                    else:
                        print("I am in else block")


async def periodic_retrieval():
    while True:
        await asyncio.gather(
            cache_pair_stablecoin_exchange_rates(),
            # TODO: create task that runs audit protocol fetches and uses the exchange rates stored earlier to
            #       calculate and cache liquidty information/change in US DOLLARS in Redis
            asyncio.sleep(120)  # run every 2 minutes
        )


def verifier_crash_cb(fut: asyncio.Future):
    try:
        exc = fut.exception()
    except asyncio.CancelledError:
        retrieval_logger.error('Respawning task for populating pair contracts, involved tokens and their metadata...')
        t = asyncio.ensure_future(periodic_retrieval())
        t.add_done_callback(verifier_crash_cb)
    except Exception as e:
        retrieval_logger.error('retrieval task crashed')
        retrieval_logger.error(e, exc_info=True)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    f = asyncio.ensure_future(periodic_retrieval())
    f.add_done_callback(verifier_crash_cb)
    try:
        asyncio.get_event_loop().run_until_complete(asyncio.gather(f))
    except:
        asyncio.get_event_loop().stop()