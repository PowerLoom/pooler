import json

from redis import asyncio as aioredis
from web3 import Web3

from ..redis_keys import (
    uniswap_pair_cached_block_height_token_price,
)
from ..settings.config import settings as worker_settings
from pooler.utils.default_logger import logger
from pooler.utils.rpc import RpcHelper
from pooler.utils.snapshot_utils import get_eth_price_usd

pricing_logger = logger.bind(module='PowerLoom|Uniswap|Pricing')


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
            sqrtPriceLimitX96 = 0

            # Technically we just need max of 4 checks to get the price, that too only first time.
            # Check against WETH pair, if not found, check against USDC pair, if not found, check against USDT pair, if not found, check against DAI pair.
            # price = quoter.functions.quoteExactInputSingle(
            # "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 3000, 1, sqrtPriceLimitX96
            # ).call()

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
