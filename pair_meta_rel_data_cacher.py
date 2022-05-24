from uniswap_functions import (
    get_pair_per_token_metadata, SCRIPT_CLEAR_KEYS, SCRIPT_SET_EXPIRE, SCRIPT_INCR_EXPIRE, GLOBAL_RPC_RATE_LIMIT_STR,
    load_rate_limiter_scripts, PARSED_LIMITS, pair_contract_abi, get_all_pairs, get_pair, read_json_file
)
from redis_keys import (
    uniswap_pair_cached_token_price
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
import tenacity
import asyncio
import logging
import json
import os
import sys
from setproctitle import setproctitle


setproctitle(f'PowerLoom|UniswapFunctions|PairMetadataCacher')

""" Inititalize the logger """
retrieval_logger = logging.getLogger('PowerLoom|UniswapFunctions|PairMetadataCacher')
retrieval_logger.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(levelname)-8s %(name)-4s %(asctime)s %(msecs)d %(module)s-%(funcName)s: %(message)s")
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(formatter)
stdout_handler.setLevel(logging.DEBUG)
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.ERROR)

if os.path.exists('static/cached_pair_addresses.json'):
    f = open('static/cached_pair_addresses.json', 'r')
    CACHED_PAIR_CONTRACTS = json.loads(f.read())
else:
    CACHED_PAIR_CONTRACTS = list()

w3 = Web3(Web3.HTTPProvider(settings.RPC.MATIC[0]))

router_contract_obj = w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.IUNISWAP_V2_ROUTER),
    abi=read_json_file('./abis/UniswapV2Router.json')
)
retrieval_logger.debug("Got uniswap v2 router object")


@provide_async_redis_conn_insta
async def cache_pair_meta_data(redis_conn: aioredis.Redis = None):
    try:
        # TODO: we can cache cached_pair_addresses content with expiry date

        if len(CACHED_PAIR_CONTRACTS) <= 0:
            return []

        for pair_contract_address in CACHED_PAIR_CONTRACTS:

            pair_address = Web3.toChecksumAddress(pair_contract_address)
            # print(f"pair_add:{pair_contract_address}")

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
                        aioredis.exceptions.ConnectionError, aioredis.exceptions.TimeoutError,
                        aioredis.exceptions.ResponseError
                ) as e:
                    # shit can happen while each limit check call hits Redis, handle appropriately
                    retrieval_logger.debug('Bypassing rate limit check for appID because of Redis exception: ' + str(
                        {'appID': app_id, 'exception': e}))
                else:
                    can_request = True
            if can_request:
                try:
                    # pair contract
                    pair = w3.eth.contract(
                        address=Web3.toChecksumAddress(pair_address),
                        abi=pair_contract_abi
                    )
                    x = await get_pair_per_token_metadata(
                        pair_contract_obj=pair,
                        pair_address=Web3.toChecksumAddress(pair_address),
                        loop=asyncio.get_running_loop()
                    )
                    # retrieval_logger.debug('Got pair contract per token metadata: %s', x)
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


async def get_token_price_against_stablecoins(pair_per_token_metadata, ev_loop, redis_conn):
    token0_USD_price = None
    token1_USD_price = None
    WETH_USD_price = None
    stable_coins_addresses = {
        "USDT": Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDT),
        "DAI": Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.DAI),
        "USDC": Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDC)
    }
    stable_coins_decimals = {
        "USDT": 6,
        "DAI": 18,
        "USDC": 6
    }

    if Web3.toChecksumAddress(pair_per_token_metadata['token0']['address']) in list(stable_coins_addresses.values()):
            token0_USD_price = 1
            retrieval_logger.debug("Ignored Stablecoin calculation for token0: %s - WETH - USDT conversion: %s", pair_per_token_metadata['token0']['symbol'], token0_USD_price)
            await redis_conn.set(uniswap_pair_cached_token_price.format(f"{pair_per_token_metadata['token0']['symbol']}-USDT"), token0_USD_price)
    elif Web3.toChecksumAddress(pair_per_token_metadata['token0']['address']) \
            != Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH):
        # if the token is not WETH then convert it with path token-weth-usdt
        
        # loop on all stable coins until we find price for token or stable coin
        stable_coins_len = len(stable_coins_addresses)
        for key, value in stable_coins_addresses.items():
            priceFunction_token0 = router_contract_obj.functions.getAmountsOut(
                10 ** int(pair_per_token_metadata['token0']['decimals']), [
                    Web3.toChecksumAddress(pair_per_token_metadata['token0']['address']),
                    Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH),
                    value]
            ).call
            token0_USD_price = await ev_loop.run_in_executor(func=priceFunction_token0, executor=None)
            stable_coins_len -= 1

            if token0_USD_price:
                token0_USD_price = token0_USD_price[2]/10**stable_coins_decimals[key] if token0_USD_price[2] !=0 else 0  #USDT decimals
                retrieval_logger.debug("Calculated price for token0: %s - WETH - %s conversion: %s", pair_per_token_metadata['token0']['symbol'], key, token0_USD_price)
                await redis_conn.set(uniswap_pair_cached_token_price.format(f"{pair_per_token_metadata['token0']['symbol']}-{key}"), token0_USD_price)
                break
            elif stable_coins_len <= 0:
                break
    else:
        # else just get weth-udst conversion
        priceFunction_token0 = router_contract_obj.functions.getAmountsOut(
            10 ** int(pair_per_token_metadata['token0']['decimals']), [
                Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH),
                Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDT)]
        ).call
        WETH_USD_price = await ev_loop.run_in_executor(func=priceFunction_token0, executor=None)
        WETH_USD_price = WETH_USD_price[1]/10**6 #USDT decimals
        retrieval_logger.debug("Calculated prices for token0: %s - USDT conversion: %s", pair_per_token_metadata['token0']['symbol'], WETH_USD_price)
        await redis_conn.set(uniswap_pair_cached_token_price.format("WETH-USDT"), WETH_USD_price)
    
    # check if token1 is WETH. If it is, weth-usdt conversion can be figured right here,
    # else provide full path token1-weth-usdt
    if Web3.toChecksumAddress(pair_per_token_metadata['token1']['address']) in list(stable_coins_addresses.values()):
            token1_USD_price = 1
            retrieval_logger.debug("Ignored Stablecoin calculation for token1: %s - WETH - USDT conversion: %s", pair_per_token_metadata['token1']['symbol'], token1_USD_price)
            await redis_conn.set(uniswap_pair_cached_token_price.format(f"{pair_per_token_metadata['token1']['symbol']}-USDT"), token1_USD_price)
    elif Web3.toChecksumAddress(pair_per_token_metadata['token1']['address']) \
            != Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH):
        # loop on all stable coins until we find price for token or stable coin
        stable_coins_len = len(stable_coins_addresses)
        for key, value in stable_coins_addresses.items():
            priceFunction_token1 = router_contract_obj.functions.getAmountsOut(
                10 ** int(pair_per_token_metadata['token1']['decimals']), [
                    Web3.toChecksumAddress(pair_per_token_metadata['token1']['address']),
                    Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH),
                    value]
            ).call
            token1_USD_price = await ev_loop.run_in_executor(func=priceFunction_token1, executor=None)
            stable_coins_len -= 1
            
            if token1_USD_price:                
                token1_USD_price = token1_USD_price[2]/10**stable_coins_decimals[key] if token1_USD_price[2] !=0 else 0
                retrieval_logger.debug("Calculated price for token1: %s - WETH - %s conversion: %s", pair_per_token_metadata['token1']['symbol'], key, token1_USD_price)
                await redis_conn.set(uniswap_pair_cached_token_price.format(f"{pair_per_token_metadata['token1']['symbol']}-{key}"), token1_USD_price)
                break
            elif stable_coins_len <= 0:
                break
    else:
        priceFunction_token1 = router_contract_obj.functions.getAmountsOut(
            10 ** int(pair_per_token_metadata['token1']['decimals']), [
                Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH),
                Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDT)]
        ).call
        WETH_USD_price = await ev_loop.run_in_executor(func=priceFunction_token1, executor=None)
        WETH_USD_price = WETH_USD_price[1]/10**6 #USDT decimals
        retrieval_logger.debug("Calculated prices for token1: %s - USDT conversion: %s", pair_per_token_metadata['token1']['symbol'], WETH_USD_price)
        await redis_conn.set(uniswap_pair_cached_token_price.format("WETH-USDT"), WETH_USD_price)

    return [token0_USD_price, token1_USD_price, WETH_USD_price]

#settings.UNISWAP_FUNCTIONS.RETRIAL_ATTEMPTS
@tenacity.retry(
    wait=tenacity.wait_random_exponential(multiplier=1, min=10, max=60),
    stop=stop_after_attempt(1),
    reraise=True
)
@provide_async_redis_conn_insta
async def cache_pair_stablecoin_exchange_rates(redis_conn: aioredis.Redis = None):
    await cache_pair_meta_data()
    all_pair_contracts = read_json_file('static/cached_pair_addresses.json')
    ev_loop = asyncio.get_running_loop()
    # # # prepare for rate limit check
    redis_storage = AsyncRedisStorage(await load_rate_limiter_scripts(redis_conn), redis_conn)
    custom_limiter = AsyncFixedWindowRateLimiter(redis_storage)
    limit_incr_by = 1  # score to be incremented for each request
    app_id = settings.RPC.MATIC[0].split('/')[
        -1]  # future support for loadbalancing over multiple MaticVigil RPC appID
    key_bits = [app_id, 'eth_call']  # TODO: add unique elements that can identify a request
    # # # prepare for rate limit check - end
    for each_pair_contract in all_pair_contracts:
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
                retrieval_logger.debug('Bypassing rate limit check for appID because of Redis exception: ' + str(
                    {'appID': app_id, 'exception': e}))
            else:
                can_request = True
        # # # rate limit check - end
        if can_request:
            # retrieval_logger.debug('I can request')
            pair_contract_obj = w3.eth.contract(
                address=Web3.toChecksumAddress(each_pair_contract),
                abi=pair_contract_abi
            )
            try:
                pair_per_token_metadata = await get_pair_per_token_metadata(
                    pair_contract_obj=pair_contract_obj,
                    pair_address=Web3.toChecksumAddress(each_pair_contract),
                    loop=ev_loop
                )
                retrieval_logger.debug("Got pair token meta-data for pair contract: %s", each_pair_contract)    

                [
                    token0_USD_price, 
                    token1_USD_price, 
                    WETH_USD_price
                ] = await get_token_price_against_stablecoins(pair_per_token_metadata, ev_loop, redis_conn)
            except Exception as err:
                # pair_contract price can't retrieved, this is mostly with sepcific coins log it and fetch price for newer ones
                retrieval_logger.error(f"Failed to fetch token price | error_msg: {str(err)} | contract: {each_pair_contract}", exc_info=True)

        else:
            retrieval_logger.debug('I cant request')

async def get_aiohttp_cache() -> aiohttp.ClientSession:
    basic_rpc_connector = aiohttp.TCPConnector(limit=settings['rlimit']['file_descriptors'])
    aiohttp_client_basic_rpc_session = aiohttp.ClientSession(connector=basic_rpc_connector)
    return aiohttp_client_basic_rpc_session

async def periodic_retrieval():
    session = await get_aiohttp_cache()
    while True:
        await asyncio.gather(
            cache_pair_stablecoin_exchange_rates(),
            asyncio.sleep(120)  # run atleast 'x' seconds not sleep for x seconds
        )
        retrieval_logger.debug('Completed one cycle of pair meta data cache.........')
    session.close()


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
        asyncio.get_event_loop().run_until_complete(f)
    except:
        asyncio.get_event_loop().stop()
