import asyncio
import json

from redis import asyncio as aioredis
from web3 import Web3

from pooler.callback_modules.redis_keys import uniswap_eth_usd_price_zset
from pooler.callback_modules.redis_keys import (
    uniswap_pair_cached_block_height_token_price,
)
from pooler.callback_modules.settings.config import settings as worker_settings
from pooler.callback_modules.uniswap.constants import factory_contract_obj
from pooler.callback_modules.uniswap.constants import pair_contract_abi
from pooler.callback_modules.uniswap.constants import router_contract_abi
from pooler.callback_modules.uniswap.constants import tokens_decimals
from pooler.callback_modules.uniswap.helpers import get_pair
from pooler.callback_modules.uniswap.helpers import get_pair_metadata
from pooler.settings.config import settings
from pooler.utils.default_logger import format_exception
from pooler.utils.default_logger import logger
from pooler.utils.exceptions import RPCException
from pooler.utils.redis.redis_conn import provide_async_redis_conn_insta
from pooler.utils.rpc import get_contract_abi_dict
from pooler.utils.rpc import rpc_helper

pricing_logger = logger.bind(module='PowerLoom|Uniswap|Pricing')


@provide_async_redis_conn_insta
async def get_eth_price_usd(
    from_block,
    to_block,
    redis_conn: aioredis.Redis = None,
):
    """
    returns the price of eth in usd at a given block height
    """

    try:
        eth_price_usd_dict = dict()
        redis_cache_mapping = dict()

        if from_block != 'latest' and to_block != 'latest':
            cached_price_dict = await redis_conn.zrangebyscore(
                name=uniswap_eth_usd_price_zset,
                min=int(from_block),
                max=int(to_block),
            )
            if cached_price_dict and len(cached_price_dict) == to_block - (
                from_block - 1
            ):
                price_dict = {
                    json.loads(
                        price.decode(
                            'utf-8',
                        ),
                    )[
                        'blockHeight'
                    ]: json.loads(price.decode('utf-8'))['price']
                    for price in cached_price_dict
                }
                return price_dict

        # fetch metadata to find order of each token in given pairs
        (
            dai_eth_pair_metadata,
            usdc_eth_pair_metadata,
            usdt_eth_pair_metadata,
        ) = await asyncio.gather(
            get_pair_metadata(
                pair_address=worker_settings.contract_addresses.DAI_WETH_PAIR,
                redis_conn=redis_conn,
            ),
            get_pair_metadata(
                pair_address=worker_settings.contract_addresses.USDC_WETH_PAIR,
                redis_conn=redis_conn,
            ),
            get_pair_metadata(
                pair_address=worker_settings.contract_addresses.USDT_WETH_PAIR,
                redis_conn=redis_conn,
            ),
        )
        # check if stable it token0 or token1
        dai_token_order = (
            0
            if Web3.toChecksumAddress(
                dai_eth_pair_metadata['token0']['address'],
            ) ==
            Web3.toChecksumAddress(worker_settings.contract_addresses.DAI)
            else 1
        )
        usdc_token_order = (
            0
            if Web3.toChecksumAddress(
                usdc_eth_pair_metadata['token0']['address'],
            ) ==
            Web3.toChecksumAddress(worker_settings.contract_addresses.USDC)
            else 1
        )
        usdt_token_order = (
            0
            if Web3.toChecksumAddress(
                usdt_eth_pair_metadata['token0']['address'],
            ) ==
            Web3.toChecksumAddress(worker_settings.contract_addresses.USDT)
            else 1
        )

        # create dictionary of ABI {function_name -> {signature, abi, input, output}}
        pair_abi_dict = get_contract_abi_dict(pair_contract_abi)

        # NOTE: We can further optimize below call by batching them all,
        # but that would be a large batch call for RPC node
        dai_eth_pair_reserves_list = await rpc_helper.batch_eth_call_on_block_range(
            abi_dict=pair_abi_dict,
            function_name='getReserves',
            contract_address=worker_settings.contract_addresses.DAI_WETH_PAIR,
            from_block=from_block,
            to_block=to_block,
        )
        usdc_eth_pair_reserves_list = await rpc_helper.batch_eth_call_on_block_range(
            abi_dict=pair_abi_dict,
            function_name='getReserves',
            contract_address=worker_settings.contract_addresses.USDC_WETH_PAIR,
            from_block=from_block,
            to_block=to_block,
        )
        eth_usdt_pair_reserves_list = await rpc_helper.batch_eth_call_on_block_range(
            abi_dict=pair_abi_dict,
            function_name='getReserves',
            contract_address=worker_settings.contract_addresses.USDT_WETH_PAIR,
            from_block=from_block,
            to_block=to_block,
        )

        block_count = 0
        for block_num in range(from_block, to_block + 1):
            dai_eth_pair_dai_reserve = (
                dai_eth_pair_reserves_list[block_count][dai_token_order] /
                10 ** tokens_decimals['DAI']
            )
            dai_eth_pair_eth_reserve = (
                dai_eth_pair_reserves_list[block_count][1 - dai_token_order] /
                10 ** tokens_decimals['WETH']
            )
            dai_price = dai_eth_pair_dai_reserve / dai_eth_pair_eth_reserve

            usdc_eth_pair_usdc_reserve = (
                usdc_eth_pair_reserves_list[block_count][usdc_token_order] /
                10 ** tokens_decimals['USDC']
            )
            usdc_eth_pair_eth_reserve = (
                usdc_eth_pair_reserves_list[block_count][1 - usdc_token_order] /
                10 ** tokens_decimals['WETH']
            )
            usdc_price = usdc_eth_pair_usdc_reserve / usdc_eth_pair_eth_reserve

            usdt_eth_pair_usdt_reserve = (
                eth_usdt_pair_reserves_list[block_count][usdt_token_order] /
                10 ** tokens_decimals['USDT']
            )
            usdt_eth_pair_eth_reserve = (
                eth_usdt_pair_reserves_list[block_count][1 - usdt_token_order] /
                10 ** tokens_decimals['WETH']
            )
            usdt_price = usdt_eth_pair_usdt_reserve / usdt_eth_pair_eth_reserve

            total_eth_liquidity = (
                dai_eth_pair_eth_reserve +
                usdc_eth_pair_eth_reserve +
                usdt_eth_pair_eth_reserve
            )

            daiWeight = dai_eth_pair_eth_reserve / total_eth_liquidity
            usdcWeight = usdc_eth_pair_eth_reserve / total_eth_liquidity
            usdtWeight = usdt_eth_pair_eth_reserve / total_eth_liquidity

            eth_price_usd = (
                daiWeight * dai_price +
                usdcWeight * usdc_price +
                usdtWeight * usdt_price
            )

            eth_price_usd_dict[block_num] = float(eth_price_usd)
            redis_cache_mapping[
                json.dumps(
                    {'blockHeight': block_num, 'price': float(eth_price_usd)},
                )
            ] = int(block_num)
            block_count += 1

        # cache price at height
        if from_block != 'latest' and to_block != 'latest':
            await asyncio.gather(
                redis_conn.zadd(
                    name=uniswap_eth_usd_price_zset,
                    mapping=redis_cache_mapping,
                ),
                redis_conn.zremrangebyscore(
                    name=uniswap_eth_usd_price_zset,
                    min=0,
                    max=int(from_block) - settings.epoch.height * 4,
                ),
            )

        return eth_price_usd_dict

    except Exception as err:
        pricing_logger.opt(exception=True).error(
            f'RPC ERROR failed to fetch ETH price, error_msg:{err}',
        )
        raise err


async def get_token_pair_price_and_white_token_reserves(
    pair_address,
    from_block,
    to_block,
    pair_metadata,
    white_token,
    redis_conn,
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

        raise RPCException(
            request={'from_block': from_block, 'to_block': to_block},
            response=pair_reserves_list,
            underlying_exception=None,
            extra_info={
                'msg': (
                    'Token pair based price RPC batch call error:'
                    f' {pair_reserves_list}'
                ),
            },
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
    white_token_metadata,
    redis_conn,
):
    token_derived_eth_dict = dict()

    if Web3.toChecksumAddress(
        white_token_metadata['address'],
    ) == Web3.toChecksumAddress(worker_settings.contract_addresses.WETH):
        # set derived eth as 1 if token is weth
        for block_num in range(from_block, to_block + 1):
            token_derived_eth_dict[block_num] = 1

        return token_derived_eth_dict

    # get white
    router_abi_dict = get_contract_abi_dict(router_contract_abi)
    token_derived_eth_list = await rpc_helper.batch_eth_call_on_block_range(
        abi_dict=router_abi_dict,
        function_name='getAmountsOut',
        contract_address=worker_settings.contract_addresses.iuniswap_v2_router,
        from_block=from_block,
        to_block=to_block,
        params=[
            10 ** int(white_token_metadata['decimals']),
            [
                Web3.toChecksumAddress(white_token_metadata['address']),
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
        raise RPCException(
            request={'from_block': from_block, 'to_block': to_block},
            response=token_derived_eth_list,
            underlying_exception=None,
            extra_info={
                'msg': (
                    'Error: failed to fetch token derived eth RPC batch call'
                    f' error: {token_derived_eth_list}'
                ),
            },
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

    return token_derived_eth_dict


async def get_token_price_in_block_range(
    token_metadata,
    from_block,
    to_block,
    redis_conn: aioredis.Redis,
    debug_log=True,
):
    """
    returns the price of a token at a given block range
    """
    try:
        token_price_dict = dict()

        # check if cahce exist for given epoch
        if from_block != 'latest' and to_block != 'latest':
            cached_price_dict = await redis_conn.zrangebyscore(
                name=uniswap_pair_cached_block_height_token_price.format(
                    Web3.toChecksumAddress(token_metadata['address']),
                ),
                min=int(from_block),
                max=int(to_block),
            )
            if cached_price_dict and len(cached_price_dict) == to_block - (
                from_block - 1
            ):
                price_dict = {
                    json.loads(
                        price.decode(
                            'utf-8',
                        ),
                    )[
                        'blockHeight'
                    ]: json.loads(price.decode('utf-8'))['price']
                    for price in cached_price_dict
                }
                return price_dict

        if Web3.toChecksumAddress(
            token_metadata['address'],
        ) == Web3.toChecksumAddress(worker_settings.contract_addresses.WETH):
            token_price_dict = await get_eth_price_usd(
                from_block=from_block,
                to_block=to_block,
                redis_conn=redis_conn,
            )
        else:
            token_eth_price_dict = dict()

            for white_token in worker_settings.uniswap_v2_whitelist:
                white_token = Web3.toChecksumAddress(white_token)
                pairAddress = await get_pair(
                    factory_contract_obj,
                    white_token,
                    token_metadata['address'],
                    redis_conn,
                )
                if pairAddress != '0x0000000000000000000000000000000000000000':
                    new_pair_metadata = await get_pair_metadata(
                        pair_address=pairAddress,
                        redis_conn=redis_conn,
                    )
                    white_token_metadata = (
                        new_pair_metadata['token0']
                        if white_token == new_pair_metadata['token0']['address']
                        else new_pair_metadata['token1']
                    )

                    (
                        white_token_price_dict,
                        white_token_reserves_dict,
                    ) = await get_token_pair_price_and_white_token_reserves(
                        pair_address=pairAddress,
                        from_block=from_block,
                        to_block=to_block,
                        pair_metadata=new_pair_metadata,
                        white_token=white_token,
                        redis_conn=redis_conn,
                    )
                    white_token_derived_eth_dict = await get_token_derived_eth(
                        from_block=from_block,
                        to_block=to_block,
                        white_token_metadata=white_token_metadata,
                        redis_conn=redis_conn,
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
                        token_eth_price_dict[
                            block_num
                        ] = white_token_price_dict.get(
                            block_num,
                        ) * white_token_derived_eth_dict.get(
                            block_num,
                        )

                    # if reserves are less than threshold then try next whitelist token pair
                    if less_than_minimum_liquidity:
                        token_eth_price_dict = {}
                        continue

                    break

            if len(token_eth_price_dict) > 0:
                eth_usd_price_dict = await get_eth_price_usd(
                    from_block=from_block,
                    to_block=to_block,
                    redis_conn=redis_conn,
                )
                for block_num in range(from_block, to_block + 1):
                    token_price_dict[block_num] = token_eth_price_dict.get(
                        block_num,
                        0,
                    ) * eth_usd_price_dict.get(block_num, 0)
            else:
                for block_num in range(from_block, to_block + 1):
                    token_price_dict[block_num] = 0

            if debug_log:
                pricing_logger.debug(
                    (
                        f"{token_metadata['symbol']}: price is"
                        f' {token_price_dict} | its eth price is'
                        f' {token_eth_price_dict}'
                    ),
                )

        # cache price at height
        if (
            from_block != 'latest' and
            to_block != 'latest' and
            len(token_price_dict) > 0
        ):
            redis_cache_mapping = {
                json.dumps({'blockHeight': height, 'price': price}): int(
                    height,
                )
                for height, price in token_price_dict.items()
            }

            await redis_conn.zadd(
                name=uniswap_pair_cached_block_height_token_price.format(
                    Web3.toChecksumAddress(token_metadata['address']),
                ),
                # timestamp so zset do not ignore same height on multiple heights
                mapping=redis_cache_mapping,
            )

        return token_price_dict

    except Exception as err:
        pricing_logger.opt(exception=True, lazy=True).trace(
            (
                'Error while calculating price of token:'
                f" {token_metadata['symbol']} | {token_metadata['address']}|"
                ' err: {err}'
            ),
            err=lambda: format_exception(err),
        )
        raise RPCException(
            request={
                'contract': token_metadata['address'],
                'from_block': from_block,
                'to_block': to_block,
            },
            response={},
            underlying_exception=None,
            extra_info={'msg': f'rpc error: {str(err)}'},
        ) from err
