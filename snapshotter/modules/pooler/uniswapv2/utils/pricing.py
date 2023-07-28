import asyncio
import json

from redis import asyncio as aioredis
from web3 import Web3

from ..redis_keys import (
    uniswap_pair_cached_block_height_token_price,
)
from ..redis_keys import (
    uniswap_token_derived_eth_cached_block_height,
)
from ..settings.config import settings as worker_settings
from .constants import factory_contract_obj
from .constants import pair_contract_abi
from .constants import router_contract_abi
from .constants import tokens_decimals
from .helpers import get_pair
from .helpers import get_pair_metadata
from snapshotter.utils.default_logger import logger
from snapshotter.utils.redis.redis_keys import source_chain_epoch_size_key
from snapshotter.utils.rpc import get_contract_abi_dict
from snapshotter.utils.rpc import RpcHelper
from snapshotter.utils.snapshot_utils import get_eth_price_usd

pricing_logger = logger.bind(module='PowerLoom|Uniswap|Pricing')


async def get_token_pair_price_and_white_token_reserves(
    pair_address,
    from_block,
    to_block,
    pair_metadata,
    white_token,
    redis_conn,
    rpc_helper: RpcHelper,
):
    """
    Function to get:
    1. token price based on pair reserves of both token: token0Price = token1Price/token0Price
    2. whitelisted token reserves

    We can write different function for each value, but to optimize we are reusing reserves value
    """
    token_price_dict = dict()
    white_token_reserves_dict = dict()

    # get white
    pair_abi_dict = get_contract_abi_dict(pair_contract_abi)
    pair_reserves_list = await rpc_helper.batch_eth_call_on_block_range(
        abi_dict=pair_abi_dict,
        function_name='getReserves',
        contract_address=pair_address,
        from_block=from_block,
        to_block=to_block,
        redis_conn=redis_conn,
    )

    if len(pair_reserves_list) < to_block - (from_block - 1):
        pricing_logger.trace(
            (
                'Unable to get pair price and white token reserves'
                'from_block: {}, to_block: {}, pair_reserves_list: {}'
            ),
            from_block,
            to_block,
            pair_reserves_list,
        )

        raise Exception(
            'Unable to get pair price and white token reserves'
            f'from_block: {from_block}, to_block: {to_block}, '
            f'got result: {pair_reserves_list}',
        )

    index = 0
    for block_num in range(from_block, to_block + 1):
        token_price = 0

        pair_reserve_token0 = pair_reserves_list[index][0] / 10 ** int(
            pair_metadata['token0']['decimals'],
        )
        pair_reserve_token1 = pair_reserves_list[index][1] / 10 ** int(
            pair_metadata['token1']['decimals'],
        )

        if float(pair_reserve_token0) == float(0) or float(
            pair_reserve_token1,
        ) == float(0):
            token_price_dict[block_num] = token_price
            white_token_reserves_dict[block_num] = 0
        elif (
            Web3.toChecksumAddress(pair_metadata['token0']['address']) ==
            white_token
        ):
            token_price_dict[block_num] = float(
                pair_reserve_token0 / pair_reserve_token1,
            )
            white_token_reserves_dict[block_num] = pair_reserve_token0
        else:
            token_price_dict[block_num] = float(
                pair_reserve_token1 / pair_reserve_token0,
            )
            white_token_reserves_dict[block_num] = pair_reserve_token1

        index += 1

    return token_price_dict, white_token_reserves_dict


async def get_token_derived_eth(
    from_block,
    to_block,
    token_metadata,
    redis_conn,
    rpc_helper: RpcHelper,
):
    token_derived_eth_dict = dict()
    token_address = Web3.toChecksumAddress(
        token_metadata['address'],
    )
    if token_address == Web3.toChecksumAddress(worker_settings.contract_addresses.WETH):
        # set derived eth as 1 if token is weth
        for block_num in range(from_block, to_block + 1):
            token_derived_eth_dict[block_num] = 1

        return token_derived_eth_dict

    cached_derived_eth_dict = await redis_conn.zrangebyscore(
        name=uniswap_token_derived_eth_cached_block_height.format(
            token_address,
        ),
        min=int(from_block),
        max=int(to_block),
    )
    if cached_derived_eth_dict and len(cached_derived_eth_dict) == to_block - (
        from_block - 1
    ):
        token_derived_eth_dict = {
            json.loads(
                price.decode(
                    'utf-8',
                ),
            )[
                'blockHeight'
            ]: json.loads(price.decode('utf-8'))['price']
            for price in cached_derived_eth_dict
        }
        return token_derived_eth_dict
    # get white
    router_abi_dict = get_contract_abi_dict(router_contract_abi)
    token_derived_eth_list = await rpc_helper.batch_eth_call_on_block_range(
        abi_dict=router_abi_dict,
        function_name='getAmountsOut',
        contract_address=worker_settings.contract_addresses.iuniswap_v2_router,
        from_block=from_block,
        to_block=to_block,
        redis_conn=redis_conn,
        params=[
            10 ** int(token_metadata['decimals']),
            [
                Web3.toChecksumAddress(token_metadata['address']),
                Web3.toChecksumAddress(worker_settings.contract_addresses.WETH),
            ],
        ],
    )

    if len(token_derived_eth_list) < to_block - (from_block - 1):
        pricing_logger.trace(
            (
                'Unable to get token derived eth'
                'from_block: {}, to_block: {}, token_derived_eth_list: {}'
            ),
            from_block,
            to_block,
            token_derived_eth_list,
        )

        raise Exception(
            'Unable to get token derived eth'
            f'from_block: {from_block}, to_block: {to_block}, '
            f'got result: {token_derived_eth_list}',
        )

    index = 0
    for block_num in range(from_block, to_block + 1):
        if not token_derived_eth_list[index]:
            token_derived_eth_dict[block_num] = 0

        _, derivedEth = token_derived_eth_list[index][0]
        token_derived_eth_dict[block_num] = (
            derivedEth / 10 ** tokens_decimals['WETH'] if derivedEth != 0 else 0
        )
        index += 1

    if (
        len(token_derived_eth_dict) > 0
    ):
        redis_cache_mapping = {
            json.dumps({'blockHeight': height, 'price': price}): int(
                height,
            )
            for height, price in token_derived_eth_dict.items()
        }
        source_chain_epoch_size = int(await redis_conn.get(source_chain_epoch_size_key()))
        await asyncio.gather(
            redis_conn.zadd(
                name=uniswap_token_derived_eth_cached_block_height.format(
                    token_address,
                ),
                # timestamp so zset do not ignore same height on multiple heights
                mapping=redis_cache_mapping,
            ),

            redis_conn.zremrangebyscore(
                name=uniswap_token_derived_eth_cached_block_height.format(
                    token_address,
                ),
                min=0,
                max=int(from_block) - source_chain_epoch_size * 4,
            ),
        )

    return token_derived_eth_dict


async def get_token_price_in_block_range(
    token_metadata,
    from_block,
    to_block,
    redis_conn: aioredis.Redis,
    rpc_helper: RpcHelper,
    debug_log=True,
):
    """
    returns the price of a token at a given block range
    """
    try:
        token_price_dict = dict()
        token_address = Web3.toChecksumAddress(token_metadata['address'])
        # check if cahce exist for given epoch
        cached_price_dict = await redis_conn.zrangebyscore(
            name=uniswap_pair_cached_block_height_token_price.format(
                token_address,
            ),
            min=int(from_block),
            max=int(to_block),
        )
        if cached_price_dict and len(cached_price_dict) == to_block - (from_block - 1):
            price_dict = {
                json.loads(
                    price.decode(
                        'utf-8',
                    ),
                )['blockHeight']: json.loads(price.decode('utf-8'))['price'] for price in cached_price_dict
            }
            return price_dict

        if token_address == Web3.toChecksumAddress(worker_settings.contract_addresses.WETH):
            token_price_dict = await get_eth_price_usd(
                from_block=from_block, to_block=to_block,
                redis_conn=redis_conn, rpc_helper=rpc_helper,
            )
        else:
            token_eth_price_dict = dict()

            for white_token in worker_settings.uniswap_v2_whitelist:
                white_token = Web3.toChecksumAddress(white_token)
                pairAddress = await get_pair(
                    factory_contract_obj, white_token, token_metadata['address'],
                    redis_conn, rpc_helper,
                )
                if pairAddress != '0x0000000000000000000000000000000000000000':
                    new_pair_metadata = await get_pair_metadata(
                        pair_address=pairAddress,
                        redis_conn=redis_conn,
                        rpc_helper=rpc_helper,
                    )
                    white_token_metadata = new_pair_metadata['token0'] if white_token == new_pair_metadata[
                        'token0'
                    ]['address'] else new_pair_metadata['token1']

                    (
                        white_token_price_dict,
                        white_token_reserves_dict,
                    ) = await get_token_pair_price_and_white_token_reserves(
                        pair_address=pairAddress, from_block=from_block, to_block=to_block,
                        pair_metadata=new_pair_metadata, white_token=white_token, redis_conn=redis_conn,
                        rpc_helper=rpc_helper,
                    )
                    white_token_derived_eth_dict = await get_token_derived_eth(
                        from_block=from_block, to_block=to_block, token_metadata=white_token_metadata,
                        redis_conn=redis_conn, rpc_helper=rpc_helper,
                    )

                    less_than_minimum_liquidity = False
                    for block_num in range(from_block, to_block + 1):

                        white_token_reserves = white_token_reserves_dict.get(
                            block_num,
                        ) * white_token_derived_eth_dict.get(block_num)

                        # ignore if reservers are less than threshold
                        if white_token_reserves < 1:
                            less_than_minimum_liquidity = True
                            break

                        # else store eth price in dictionary
                        token_eth_price_dict[block_num] = white_token_price_dict.get(
                            block_num,
                        ) * white_token_derived_eth_dict.get(block_num)

                    # if reserves are less than threshold then try next whitelist token pair
                    if less_than_minimum_liquidity:
                        token_eth_price_dict = {}
                        continue

                    break

            if len(token_eth_price_dict) > 0:
                eth_usd_price_dict = await get_eth_price_usd(
                    from_block=from_block, to_block=to_block, redis_conn=redis_conn,
                    rpc_helper=rpc_helper,
                )
                for block_num in range(from_block, to_block + 1):
                    token_price_dict[block_num] = token_eth_price_dict.get(
                        block_num, 0,
                    ) * eth_usd_price_dict.get(block_num, 0)
            else:
                for block_num in range(from_block, to_block + 1):
                    token_price_dict[block_num] = 0

            if debug_log:
                pricing_logger.debug(
                    f"{token_metadata['symbol']}: price is {token_price_dict}"
                    f' | its eth price is {token_eth_price_dict}',
                )

        # cache price at height
        if len(token_price_dict) > 0:
            redis_cache_mapping = {
                json.dumps({'blockHeight': height, 'price': price}): int(
                    height,
                ) for height, price in token_price_dict.items()
            }

            await redis_conn.zadd(
                name=uniswap_pair_cached_block_height_token_price.format(
                    Web3.toChecksumAddress(token_metadata['address']),
                ),
                mapping=redis_cache_mapping,  # timestamp so zset do not ignore same height on multiple heights
            )

        return token_price_dict

    except Exception as err:
        pricing_logger.opt(exception=True, lazy=True).trace(
            (
                'Error while calculating price of token:'
                f" {token_metadata['symbol']} | {token_metadata['address']}|"
                ' err: {err}'
            ),
            err=lambda: str(err),
        )
        raise err
