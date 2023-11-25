import asyncio
import json

from redis import asyncio as aioredis

from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import logger
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.redis.redis_keys import cached_block_details_at_height
from snapshotter.utils.redis.redis_keys import source_chain_epoch_size_key
from snapshotter.utils.redis.redis_keys import uniswap_eth_usd_price_zset
from snapshotter.utils.rpc import get_contract_abi_dict
from snapshotter.utils.rpc import RpcHelper


snapshot_util_logger = logger.bind(module='Powerloom|Snapshotter|SnapshotUtilLogger')

# TODO: Move this to preloader config
DAI_WETH_PAIR = '0xa478c2975ab1ea89e8196811f51a7b7ade33eb11'
USDC_WETH_PAIR = '0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc'
USDT_WETH_PAIR = '0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852'

TOKENS_DECIMALS = {
    'USDT': 6,
    'DAI': 18,
    'USDC': 6,
    'WETH': 18,
}

# LOAD ABIs
pair_contract_abi = read_json_file(
    settings.pair_contract_abi,
    snapshot_util_logger,
)


async def get_eth_price_usd(
    from_block,
    to_block,
    redis_conn: aioredis.Redis,
    rpc_helper: RpcHelper,
):
    """
    Fetches the ETH price in USD for a given block range using Uniswap DAI/ETH, USDC/ETH and USDT/ETH pairs.

    Args:
        from_block (int): The starting block number.
        to_block (int): The ending block number.
        redis_conn (aioredis.Redis): The Redis connection object.
        rpc_helper (RpcHelper): The RPC helper object.

    Returns:
        dict: A dictionary containing the ETH price in USD for each block in the given range.
    """
    try:
        eth_price_usd_dict = dict()
        redis_cache_mapping = dict()

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

        pair_abi_dict = get_contract_abi_dict(pair_contract_abi)

        # NOTE: We can further optimize below call by batching them all,
        # but that would be a large batch call for RPC node
        dai_eth_pair_reserves_list = await rpc_helper.batch_eth_call_on_block_range(
            abi_dict=pair_abi_dict,
            function_name='getReserves',
            contract_address=DAI_WETH_PAIR,
            from_block=from_block,
            to_block=to_block,
            redis_conn=redis_conn,
        )
        usdc_eth_pair_reserves_list = await rpc_helper.batch_eth_call_on_block_range(
            abi_dict=pair_abi_dict,
            function_name='getReserves',
            contract_address=USDC_WETH_PAIR,
            from_block=from_block,
            to_block=to_block,
            redis_conn=redis_conn,
        )
        eth_usdt_pair_reserves_list = await rpc_helper.batch_eth_call_on_block_range(
            abi_dict=pair_abi_dict,
            function_name='getReserves',
            contract_address=USDT_WETH_PAIR,
            from_block=from_block,
            to_block=to_block,
            redis_conn=redis_conn,
        )

        block_count = 0
        for block_num in range(from_block, to_block + 1):
            dai_eth_pair_dai_reserve = (
                dai_eth_pair_reserves_list[block_count][0] /
                10 ** TOKENS_DECIMALS['DAI']
            )
            dai_eth_pair_eth_reserve = (
                dai_eth_pair_reserves_list[block_count][1] /
                10 ** TOKENS_DECIMALS['WETH']
            )
            dai_price = dai_eth_pair_dai_reserve / dai_eth_pair_eth_reserve

            usdc_eth_pair_usdc_reserve = (
                usdc_eth_pair_reserves_list[block_count][0] /
                10 ** TOKENS_DECIMALS['USDC']
            )
            usdc_eth_pair_eth_reserve = (
                usdc_eth_pair_reserves_list[block_count][1] /
                10 ** TOKENS_DECIMALS['WETH']
            )
            usdc_price = usdc_eth_pair_usdc_reserve / usdc_eth_pair_eth_reserve

            usdt_eth_pair_usdt_reserve = (
                eth_usdt_pair_reserves_list[block_count][1] /
                10 ** TOKENS_DECIMALS['USDT']
            )
            usdt_eth_pair_eth_reserve = (
                eth_usdt_pair_reserves_list[block_count][0] /
                10 ** TOKENS_DECIMALS['WETH']
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
        source_chain_epoch_size = int(await redis_conn.get(source_chain_epoch_size_key()))
        await asyncio.gather(
            redis_conn.zadd(
                name=uniswap_eth_usd_price_zset,
                mapping=redis_cache_mapping,
            ),
            redis_conn.zremrangebyscore(
                name=uniswap_eth_usd_price_zset,
                min=0,
                max=int(from_block) - source_chain_epoch_size * 4,
            ),
        )

        return eth_price_usd_dict

    except Exception as err:
        snapshot_util_logger.opt(exception=settings.logs.trace_enabled).error(
            f'RPC ERROR failed to fetch ETH price, error_msg:{err}',
        )
        raise err


async def get_block_details_in_block_range(
    from_block,
    to_block,
    redis_conn: aioredis.Redis,
    rpc_helper: RpcHelper,
):
    """
    Fetches block details for a given range of block numbers.

    Args:
        from_block (int): The starting block number.
        to_block (int): The ending block number.
        redis_conn (aioredis.Redis): The Redis connection object.
        rpc_helper (RpcHelper): The RPC helper object.

    Returns:
        dict: A dictionary containing block details for each block number in the given range.
    """
    try:
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

        rpc_batch_block_details = await rpc_helper.batch_eth_get_block(from_block, to_block, redis_conn)

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
                'transactions': block_details.get('transactions', []),
            }

            block_details_dict[block_num] = block_details
            redis_cache_mapping[json.dumps(block_details)] = int(block_num)
            block_num += 1

        # add new block details and prune all block details older than latest 3 epochs
        source_chain_epoch_size = int(await redis_conn.get(source_chain_epoch_size_key()))
        await asyncio.gather(
            redis_conn.zadd(
                name=cached_block_details_at_height,
                mapping=redis_cache_mapping,
            ),
            redis_conn.zremrangebyscore(
                name=cached_block_details_at_height,
                min=0,
                max=int(from_block) - source_chain_epoch_size * 3,
            ),
        )
        return block_details_dict

    except Exception as e:
        snapshot_util_logger.opt(exception=settings.logs.trace_enabled, lazy=True).trace(
            'Unable to fetch block details, error_msg:{err}',
            err=lambda: str(e),
        )

        raise e


async def warm_up_cache_for_snapshot_constructors(
    from_block,
    to_block,
    redis_conn: aioredis.Redis,
    rpc_helper: RpcHelper,
):
    """
    Warms up the cache for snapshot constructors by fetching Ethereum price and block details
    in the given block range.

    Args:
        from_block (int): The starting block number.
        to_block (int): The ending block number.
        redis_conn (aioredis.Redis): The Redis connection object.
        rpc_helper (RpcHelper): The RPC helper object.

    Returns:
        None
    """
    await asyncio.gather(
        get_eth_price_usd(
            from_block=from_block,
            to_block=to_block,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
        ),
        get_block_details_in_block_range(
            from_block=from_block,
            to_block=to_block,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
        ),
        return_exceptions=True,
    )
