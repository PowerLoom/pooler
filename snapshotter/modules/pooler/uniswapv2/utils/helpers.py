import asyncio

from redis import asyncio as aioredis
from web3 import Web3

from ..redis_keys import uniswap_pair_contract_tokens_addresses
from ..redis_keys import uniswap_pair_contract_tokens_data
from ..redis_keys import uniswap_tokens_pair_map
from ..settings.config import settings as worker_settings
from .constants import current_node
from .constants import erc20_abi
from .constants import pair_contract_abi
from snapshotter.utils.default_logger import logger
from snapshotter.utils.rpc import RpcHelper


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
    redis_conn: aioredis.Redis,
    rpc_helper: RpcHelper,
):
    # check if pair cache exists
    pair_address_cache = await redis_conn.hget(
        uniswap_tokens_pair_map,
        f'{Web3.toChecksumAddress(token0)}-{Web3.toChecksumAddress(token1)}',
    )
    if pair_address_cache:
        pair_address_cache = pair_address_cache.decode('utf-8')
        return Web3.toChecksumAddress(pair_address_cache)

    tasks = [
        factory_contract_obj.functions.getPair(
            Web3.toChecksumAddress(token0),
            Web3.toChecksumAddress(token1),
        ),
    ]

    result = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)
    pair = result[0]
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


async def get_pair_metadata(
    pair_address,
    redis_conn: aioredis.Redis,
    rpc_helper: RpcHelper,
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
            pair_contract_obj = current_node['web3_client'].eth.contract(
                address=Web3.toChecksumAddress(pair_address),
                abi=pair_contract_abi,
            )
            token0Addr, token1Addr = await rpc_helper.web3_call(
                [
                    pair_contract_obj.functions.token0(),
                    pair_contract_obj.functions.token1(),
                ],
                redis_conn=redis_conn,
            )

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
        token0 = current_node['web3_client'].eth.contract(
            address=Web3.toChecksumAddress(token0Addr),
            abi=erc20_abi,
        )
        # token1 contract
        token1 = current_node['web3_client'].eth.contract(
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

            if maker_token1:
                [
                    token0_name,
                    token0_symbol,
                    token0_decimals,
                    token1_decimals,
                ] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)
            elif maker_token0:
                [
                    token0_decimals,
                    token1_name,
                    token1_symbol,
                    token1_decimals,
                ] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)
            else:
                [
                    token0_name,
                    token0_symbol,
                    token0_decimals,
                    token1_name,
                    token1_symbol,
                    token1_decimals,
                ] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)

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
