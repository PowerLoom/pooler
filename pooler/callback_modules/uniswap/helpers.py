import asyncio
import json
from functools import partial

from redis import asyncio as aioredis
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential
from web3 import Web3

from pooler.callback_modules.settings.config import settings as worker_settings
from pooler.callback_modules.uniswap.constants import erc20_abi
from pooler.callback_modules.uniswap.constants import global_w3_client
from pooler.callback_modules.uniswap.constants import pair_contract_abi
from pooler.settings.config import settings
from pooler.utils.default_logger import format_exception
from pooler.utils.default_logger import logger
from pooler.utils.redis.rate_limiter import check_rpc_rate_limit
from pooler.utils.redis.redis_conn import provide_async_redis_conn_insta
from pooler.utils.redis.redis_keys import cached_block_details_at_height
from pooler.utils.redis.redis_keys import uniswap_pair_contract_tokens_addresses
from pooler.utils.redis.redis_keys import uniswap_pair_contract_tokens_data
from pooler.utils.redis.redis_keys import uniswap_tokens_pair_map
from pooler.utils.rpc_helper import batch_eth_get_block
from pooler.utils.rpc_helper import inject_web3_provider_first_run
from pooler.utils.rpc_helper import inject_web3_provider_on_exception
from pooler.utils.rpc_helper import RPCException


helper_logger = logger.bind(module='PowerLoom|Uniswap|Helpers')


def get_maker_pair_data(prop):
    prop = prop.lower()
    if prop.lower() == 'name':
        return 'Maker'
    elif prop.lower() == 'symbol':
        return 'MKR'
    else:
        return 'Maker'


async def get_pair(
    factory_contract_obj,
    token0,
    token1,
    loop: asyncio.AbstractEventLoop,
    redis_conn: aioredis.Redis,
    rate_limit_lua_script_shas,
    web3_provider=global_w3_client,
):
    # check if pair cache exists
    pair_address_cache = await redis_conn.hget(
        uniswap_tokens_pair_map,
        f'{Web3.toChecksumAddress(token0)}-{Web3.toChecksumAddress(token1)}',
    )
    if pair_address_cache:
        pair_address_cache = pair_address_cache.decode('utf-8')
        return Web3.toChecksumAddress(pair_address_cache)

    # get pair from eth rpc
    pair_func = partial(
        factory_contract_obj.functions.getPair(
            Web3.toChecksumAddress(token0),
            Web3.toChecksumAddress(token1),
        ).call,
    )
    await check_rpc_rate_limit(
        parsed_limits=web3_provider.get('rate_limit', []),
        app_id=web3_provider.get('rpc_url').split('/')[-1],
        redis_conn=redis_conn,
        request_payload={'token0': token0, 'token1': token1},
        error_msg={
            'msg': (
                'exhausted_api_key_rate_limit inside uniswap_functions'
                ' get_pair fn'
            ),
        },
        logger=helper_logger,
        rate_limit_lua_script_shas=rate_limit_lua_script_shas,
        limit_incr_by=1,
    )
    pair = await loop.run_in_executor(func=pair_func, executor=None)

    # cache the pair address
    await redis_conn.hset(
        name=uniswap_tokens_pair_map,
        mapping={
            f'{Web3.toChecksumAddress(token0)}-{Web3.toChecksumAddress(token1)}': Web3.toChecksumAddress(
                pair,
            ),
        },
    )

    return pair


@inject_web3_provider_first_run
@retry(
    reraise=True,
    retry=retry_if_exception_type(RPCException),
    wait=wait_random_exponential(multiplier=2, max=10),
    stop=stop_after_attempt(worker_settings.uniswap_functions.retrial_attempts),
    before_sleep=inject_web3_provider_on_exception,
)
async def get_pair_metadata(
    pair_address,
    loop: asyncio.AbstractEventLoop,
    redis_conn: aioredis.Redis,
    rate_limit_lua_script_shas,
    web3_provider=global_w3_client,
):
    """
    returns information on the tokens contained within a pair contract - name, symbol, decimals of token0 and token1
    also returns pair symbol by concatenating {token0Symbol}-{token1Symbol}
    """
    try:
        pair_address = Web3.toChecksumAddress(pair_address)

        # check if cache exist
        (
            pair_token_addresses_cache,
            pair_tokens_data_cache,
        ) = await asyncio.gather(
            redis_conn.hgetall(
                uniswap_pair_contract_tokens_addresses.format(pair_address),
            ),
            redis_conn.hgetall(
                uniswap_pair_contract_tokens_data.format(pair_address),
            ),
        )

        # parse addresses cache or call eth rpc
        token0Addr = None
        token1Addr = None
        if pair_token_addresses_cache:
            token0Addr = Web3.toChecksumAddress(
                pair_token_addresses_cache[b'token0Addr'].decode('utf-8'),
            )
            token1Addr = Web3.toChecksumAddress(
                pair_token_addresses_cache[b'token1Addr'].decode('utf-8'),
            )
        else:
            pair_contract_obj = web3_provider['web3_client'].w3.eth.contract(
                address=Web3.toChecksumAddress(pair_address),
                abi=pair_contract_abi,
            )
            await check_rpc_rate_limit(
                parsed_limits=web3_provider.get('rate_limit', []),
                app_id=web3_provider.get('rpc_url', '').split('/')[-1],
                redis_conn=redis_conn,
                request_payload={'pair_address': pair_address},
                error_msg={
                    'msg': (
                        'exhausted_api_key_rate_limit inside uniswap_functions'
                        ' get_pair_metadata fn'
                    ),
                },
                logger=helper_logger,
                rate_limit_lua_script_shas=rate_limit_lua_script_shas,
                limit_incr_by=2,
            )

            try:
                token0Addr, token1Addr = web3_provider[
                    'web3_client'
                ].batch_call(
                    [
                        pair_contract_obj.functions.token0(),
                        pair_contract_obj.functions.token1(),
                    ],
                )
            except Exception as e:
                exc = RPCException(
                    request={
                        'pair_address': pair_address,
                        'token0': token0Addr,
                        'token1': token1Addr,
                    },
                    response=None,
                    underlying_exception=e,
                    extra_info={'msg': format_exception(e)},
                )

                helper_logger.opt(lazy=True).trace(
                    (
                        'error while getting token0 and token1 addresses for'
                        f' pair {pair_address} - {{err}}'
                    ),
                    err=lambda: str(exc),
                )
                raise exc

            await redis_conn.hset(
                name=uniswap_pair_contract_tokens_addresses.format(
                    pair_address,
                ),
                mapping={
                    'token0Addr': token0Addr,
                    'token1Addr': token1Addr,
                },
            )

        # token0 contract
        token0 = web3_provider['web3_client'].w3.eth.contract(
            address=Web3.toChecksumAddress(token0Addr),
            abi=erc20_abi,
        )
        # token1 contract
        token1 = web3_provider['web3_client'].w3.eth.contract(
            address=Web3.toChecksumAddress(token1Addr),
            abi=erc20_abi,
        )

        # parse token data cache or call eth rpc
        if pair_tokens_data_cache:
            token0_decimals = pair_tokens_data_cache[b'token0_decimals'].decode(
                'utf-8',
            )
            token1_decimals = pair_tokens_data_cache[b'token1_decimals'].decode(
                'utf-8',
            )
            token0_symbol = pair_tokens_data_cache[b'token0_symbol'].decode(
                'utf-8',
            )
            token1_symbol = pair_tokens_data_cache[b'token1_symbol'].decode(
                'utf-8',
            )
            token0_name = pair_tokens_data_cache[b'token0_name'].decode('utf-8')
            token1_name = pair_tokens_data_cache[b'token1_name'].decode('utf-8')
        else:
            tasks = list()

            # special case to handle maker token
            maker_token0 = None
            maker_token1 = None
            if Web3.toChecksumAddress(
                worker_settings.contract_addresses.MAKER,
            ) == Web3.toChecksumAddress(token0Addr):
                token0_name = get_maker_pair_data('name')
                token0_symbol = get_maker_pair_data('symbol')
                maker_token0 = True
            else:
                tasks.append(token0.functions.name())
                tasks.append(token0.functions.symbol())
            tasks.append(token0.functions.decimals())

            if Web3.toChecksumAddress(
                worker_settings.contract_addresses.MAKER,
            ) == Web3.toChecksumAddress(token1Addr):
                token1_name = get_maker_pair_data('name')
                token1_symbol = get_maker_pair_data('symbol')
                maker_token1 = True
            else:
                tasks.append(token1.functions.name())
                tasks.append(token1.functions.symbol())
            tasks.append(token1.functions.decimals())

            await check_rpc_rate_limit(
                parsed_limits=web3_provider.get('rate_limit', []),
                app_id=web3_provider.get('rpc_url', '').split('/')[-1],
                redis_conn=redis_conn,
                request_payload={'pair_address': pair_address},
                error_msg={
                    'msg': (
                        'exhausted_api_key_rate_limit inside uniswap_functions'
                        ' get_pair_metadata fn'
                    ),
                },
                logger=helper_logger,
                rate_limit_lua_script_shas=rate_limit_lua_script_shas,
                limit_incr_by=4,
            )
            try:
                if maker_token1:
                    [
                        token0_name,
                        token0_symbol,
                        token0_decimals,
                        token1_decimals,
                    ] = web3_provider['web3_client'].batch_call(
                        tasks,
                    )
                elif maker_token0:
                    [
                        token0_decimals,
                        token1_name,
                        token1_symbol,
                        token1_decimals,
                    ] = web3_provider['web3_client'].batch_call(
                        tasks,
                    )
                else:
                    [
                        token0_name,
                        token0_symbol,
                        token0_decimals,
                        token1_name,
                        token1_symbol,
                        token1_decimals,
                    ] = web3_provider['web3_client'].batch_call(tasks)
            except Exception as e:
                exc = RPCException(
                    request={
                        'pair_address': pair_address,
                        'token0': token0Addr,
                        'token1': token1Addr,
                    },
                    response=None,
                    underlying_exception=e,
                    extra_info={'msg': format_exception(e)},
                )
                helper_logger.opt(lazy=True).trace(
                    (
                        'error while getting token0 and token1 addresses for'
                        f' pair {pair_address} - {{err}}'
                    ),
                    err=lambda: str(exc),
                )
                raise exc

            await redis_conn.hset(
                name=uniswap_pair_contract_tokens_data.format(pair_address),
                mapping={
                    'token0_name': token0_name,
                    'token0_symbol': token0_symbol,
                    'token0_decimals': token0_decimals,
                    'token1_name': token1_name,
                    'token1_symbol': token1_symbol,
                    'token1_decimals': token1_decimals,
                    'pair_symbol': f'{token0_symbol}-{token1_symbol}',
                },
            )

        return {
            'token0': {
                'address': token0Addr,
                'name': token0_name,
                'symbol': token0_symbol,
                'decimals': token0_decimals,
            },
            'token1': {
                'address': token1Addr,
                'name': token1_name,
                'symbol': token1_symbol,
                'decimals': token1_decimals,
            },
            'pair': {
                'symbol': f'{token0_symbol}-{token1_symbol}',
            },
        }
    except Exception as err:
        # this will be retried in next cycle
        helper_logger.opt(exception=True).error(
            (
                f'RPC error while fetcing metadata for pair {pair_address},'
                f' error_msg:{err}'
            ),
        )
        raise err


@provide_async_redis_conn_insta
async def get_block_details_in_block_range(
    from_block,
    to_block,
    redis_conn: aioredis.Redis = None,
    rate_limit_lua_script_shas=None,
    web3_provider=global_w3_client,
):
    """
    Fetch block-details for a range of block number or a single block

    """
    try:
        if from_block != 'latest' and to_block != 'latest':
            cached_details = await redis_conn.zrangebyscore(
                name=cached_block_details_at_height,
                min=int(from_block),
                max=int(to_block),
            )

            # check if we have cached value for each block number
            if cached_details and len(cached_details) == to_block - (
                from_block - 1
            ):
                cached_details = {
                    json.loads(
                        block_detail.decode(
                            'utf-8',
                        ),
                    )[
                        'number'
                    ]: json.loads(block_detail.decode('utf-8'))
                    for block_detail in cached_details
                }
                return cached_details

        await check_rpc_rate_limit(
            parsed_limits=web3_provider.get('rate_limit', []),
            app_id=web3_provider.get('rpc_url').split('/')[-1],
            redis_conn=redis_conn,
            request_payload={'from_block': from_block, 'to_block': to_block},
            error_msg={
                'msg': (
                    'exhausted_api_key_rate_limit inside'
                    ' get_block_details_in_block_range'
                ),
            },
            logger=helper_logger,
            rate_limit_lua_script_shas=rate_limit_lua_script_shas,
            limit_incr_by=to_block - from_block + 1,
        )
        rpc_batch_block_details = batch_eth_get_block(
            rpc_endpoint=web3_provider.get(
                'rpc_url',
            ),
            from_block=from_block,
            to_block=to_block,
        )
        rpc_batch_block_details = (
            rpc_batch_block_details if rpc_batch_block_details else []
        )

        block_details_dict = dict()
        redis_cache_mapping = dict()

        block_num = from_block
        for block_details in rpc_batch_block_details:
            block_details = block_details.get('result')
            # right now we are just storing timestamp out of all block details,
            # edit this if you want to store something else
            block_details = {
                'timestamp': int(block_details.get('timestamp', None), 16),
                'number': int(block_details.get('number', None), 16),
            }

            block_details_dict[block_num] = block_details
            redis_cache_mapping[json.dumps(block_details)] = int(block_num)
            block_num += 1

        # add new block details and prune all block details older than latest 3 epochs
        if from_block != 'latest' and to_block != 'latest':
            await asyncio.gather(
                redis_conn.zadd(
                    name=cached_block_details_at_height,
                    mapping=redis_cache_mapping,
                ),
                redis_conn.zremrangebyscore(
                    name=cached_block_details_at_height,
                    min=0,
                    max=int(from_block) - settings.epoch.height * 3,
                ),
            )

        return block_details_dict

    except Exception as e:
        helper_logger.opt(exception=True, lazy=True).trace(
            'Unable to fetch block details, error_msg:{err}',
            err=lambda: format_exception(e),
        )

        raise RPCException(
            request={'from_block': from_block, 'to_block': to_block},
            response=None,
            underlying_exception=e,
            extra_info={'msg': str(e)},
        ) from e
