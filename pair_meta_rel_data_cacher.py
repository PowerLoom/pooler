from typing import AsyncIterator

import redis
from uniswap_functions import (
    get_pair_per_token_metadata, LUA_SCRIPT_SHAS, GLOBAL_RPC_RATE_LIMIT_STR, load_rate_limiter_scripts,
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
from redis_conn import RedisPoolCache
from tenacity import Retrying, wait_random_exponential, stop_after_attempt
from redis import asyncio as aioredis
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
    abi=read_json_file(settings.UNISWAP_CONTRACT_ABIS.ROUTER)
)
retrieval_logger.debug("Got uniswap v2 router object")


async def cache_pair_meta_data(redis_conn: aioredis.Redis, rate_limit_lua_script_shas: dict):
    try:
        # TODO: we can cache cached_pair_addresses content with expiry date

        if len(CACHED_PAIR_CONTRACTS) <= 0:
            return []

        for pair_contract_address in CACHED_PAIR_CONTRACTS:

            pair_address = Web3.toChecksumAddress(pair_contract_address)
            # print(f"pair_add:{pair_contract_address}")
            redis_storage = AsyncRedisStorage(rate_limit_lua_script_shas, redis_conn)
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
                        loop=asyncio.get_running_loop(),
                        redis_conn=redis_conn
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

async def get_token_price_at_block_height(token_metadata, block_height, loop: asyncio.AbstractEventLoop, debug_log=True):
    """
        returns the price of a token at a given block height
    """
    try:
        token_price = 0

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
                    retrieval_logger.debug(f"Ignored Stablecoin calculation for token0: {token_metadata['symbol']} - WETH - USDT conversion: {token_price}")

        # check if token has no pair with stablecoin and weth if so then use hardcoded path
        elif nonStable_coins_addresses.get(Web3.toChecksumAddress(token_metadata['address'])):
            contract_metadata = nonStable_coins_addresses.get(Web3.toChecksumAddress(token_metadata['address']))
            priceFunction_token0 = partial(router_contract_obj.functions.getAmountsOut(
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
                    priceFunction_token0 = partial(router_contract_obj.functions.getAmountsOut(
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
                        priceFunction_token0 = partial(router_contract_obj.functions.getAmountsOut(
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
                priceFunction_token0 = partial(router_contract_obj.functions.getAmountsOut(
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
                priceFunction_token0 = partial(router_contract_obj.functions.getAmountsOut(
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
                retrieval_logger.debug(f"Calculated price for token0: {token_metadata['symbol']} - stablecoin conversion: {token_price}")

        # if token is weth then directly check its price against stable coin
        else:
            priceFunction_token0 = partial(router_contract_obj.functions.getAmountsOut(
                10 ** int(token_metadata['decimals']), [
                    Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH),
                    Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDT)]
            ).call, block_identifier=block_height)
            token_price = await loop.run_in_executor(func=priceFunction_token0, executor=None)
            token_price = token_price[1]/10**stable_coins_decimals["USDT"] #USDT decimals
            if debug_log:
                retrieval_logger.debug(f"Calculated prices for token0: {token_metadata['symbol']} - USDT conversion: {token_price}")

    except Exception as err:
        retrieval_logger.error(f"Error: failed to fetch token price | error_msg: {str(err)} | contract: {token_metadata['address']}")
    finally:
        return float(token_price)


@tenacity.retry(
    wait=tenacity.wait_random_exponential(multiplier=1, min=10, max=60),
    stop=stop_after_attempt(1),
    reraise=True
)
async def cache_pair_stablecoin_exchange_rates(redis_conn: aioredis.Redis, rate_limit_lua_script_shas: dict):
    await cache_pair_meta_data(redis_conn, rate_limit_lua_script_shas)
    all_pair_contracts = read_json_file('static/cached_pair_addresses.json')
    ev_loop = asyncio.get_running_loop()
    # # # prepare for rate limit check
    redis_storage = AsyncRedisStorage(rate_limit_lua_script_shas, redis_conn)
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
                    loop=ev_loop,
                    redis_conn=redis_conn
                )
                retrieval_logger.debug("Got pair token meta-data for pair contract: %s", each_pair_contract)


                token0_USD_price, token1_USD_price = await asyncio.gather(
                    get_token_price_at_block_height(pair_per_token_metadata['token0'], 'latest', ev_loop),
                    get_token_price_at_block_height(pair_per_token_metadata['token1'], 'latest', ev_loop)
                )
                await redis_conn.mset({
                    uniswap_pair_cached_token_price.format(f"{pair_per_token_metadata['token0']['symbol']}-USDT"): token0_USD_price,
                    uniswap_pair_cached_token_price.format(f"{pair_per_token_metadata['token1']['symbol']}-USDT"): token1_USD_price
                })
                print(f"Price => {pair_per_token_metadata['token0']['symbol']}:{token0_USD_price} | {pair_per_token_metadata['token1']['symbol']}:{token1_USD_price}")
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
    aioredis_pool = RedisPoolCache(pool_size=20)
    await aioredis_pool.populate()
    rate_limit_lua_script_shas = await load_rate_limiter_scripts(aioredis_pool._aioredis_pool)
    while True:
        await asyncio.gather(
            cache_pair_stablecoin_exchange_rates(
                redis_conn=aioredis_pool._aioredis_pool,
                rate_limit_lua_script_shas=rate_limit_lua_script_shas
            ),
            asyncio.sleep(120)  # run atleast 'x' seconds not sleep for x seconds
        )
        retrieval_logger.debug('Completed one cycle of pair meta data cache.........')


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
