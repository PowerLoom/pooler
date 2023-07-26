import time
from typing import Dict
from typing import Optional
from typing import Union

from redis import asyncio as aioredis

from .utils.core import get_pair_reserves
from .utils.models.message_models import EpochBaseSnapshot
from .utils.models.message_models import UniswapPairTotalReservesSnapshot
from snapshotter.utils.callback_helpers import GenericProcessorSnapshot
from snapshotter.utils.default_logger import logger
from snapshotter.utils.models.message_models import PowerloomSnapshotProcessMessage
from snapshotter.utils.rpc import RpcHelper


class PairTotalReservesProcessor(GenericProcessorSnapshot):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
        self._logger = logger.bind(module='PairTotalReservesProcessor')

    async def compute(
        self,
        epoch: PowerloomSnapshotProcessMessage,
        redis_conn: aioredis.Redis,
        rpc_helper: RpcHelper,

    ) -> Optional[Dict[str, Union[int, float]]]:

        min_chain_height = epoch.begin
        max_chain_height = epoch.end

        data_source_contract_address = epoch.data_source

        epoch_reserves_snapshot_map_token0 = dict()
        epoch_prices_snapshot_map_token0 = dict()
        epoch_prices_snapshot_map_token1 = dict()
        epoch_reserves_snapshot_map_token1 = dict()
        epoch_usd_reserves_snapshot_map_token0 = dict()
        epoch_usd_reserves_snapshot_map_token1 = dict()
        max_block_timestamp = int(time.time())

        self._logger.debug(f'pair reserves {data_source_contract_address} computation init time {time.time()}')
        pair_reserve_total = await get_pair_reserves(
            pair_address=data_source_contract_address,
            from_block=min_chain_height,
            to_block=max_chain_height,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
            fetch_timestamp=True,
        )

        for block_num in range(min_chain_height, max_chain_height + 1):
            block_pair_total_reserves = pair_reserve_total.get(block_num)
            fetch_ts = True if block_num == max_chain_height else False

            epoch_reserves_snapshot_map_token0[
                f'block{block_num}'
            ] = block_pair_total_reserves['token0']
            epoch_reserves_snapshot_map_token1[
                f'block{block_num}'
            ] = block_pair_total_reserves['token1']
            epoch_usd_reserves_snapshot_map_token0[
                f'block{block_num}'
            ] = block_pair_total_reserves['token0USD']
            epoch_usd_reserves_snapshot_map_token1[
                f'block{block_num}'
            ] = block_pair_total_reserves['token1USD']

            epoch_prices_snapshot_map_token0[
                f'block{block_num}'
            ] = block_pair_total_reserves['token0Price']

            epoch_prices_snapshot_map_token1[
                f'block{block_num}'
            ] = block_pair_total_reserves['token1Price']

            if fetch_ts:
                if not block_pair_total_reserves.get('timestamp', None):
                    self._logger.error(
                        (
                            'Could not fetch timestamp against max block'
                            ' height in epoch {} - {}to calculate pair'
                            ' reserves for contract {}. Using current time'
                            ' stamp for snapshot construction'
                        ),
                        data_source_contract_address,
                        min_chain_height,
                        max_chain_height,
                    )
                else:
                    max_block_timestamp = block_pair_total_reserves.get(
                        'timestamp',
                    )
        pair_total_reserves_snapshot = UniswapPairTotalReservesSnapshot(
            **{
                'token0Reserves': epoch_reserves_snapshot_map_token0,
                'token1Reserves': epoch_reserves_snapshot_map_token1,
                'token0ReservesUSD': epoch_usd_reserves_snapshot_map_token0,
                'token1ReservesUSD': epoch_usd_reserves_snapshot_map_token1,
                'token0Prices': epoch_prices_snapshot_map_token0,
                'token1Prices': epoch_prices_snapshot_map_token1,
                'chainHeightRange': EpochBaseSnapshot(
                    begin=min_chain_height, end=max_chain_height,
                ),
                'timestamp': max_block_timestamp,
                'contract': data_source_contract_address,
            },
        )
        self._logger.debug(f'pair reserves {data_source_contract_address}, computation end time {time.time()}')

        return pair_total_reserves_snapshot
