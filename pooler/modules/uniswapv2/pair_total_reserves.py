import time
from typing import Dict
from typing import Optional
from typing import Union

from .utils.core import get_pair_reserves
from pooler.settings.config import settings
from pooler.utils.callback_helpers import CallbackAsyncWorker
from pooler.utils.models.message_models import EpochBase
from pooler.utils.models.message_models import UniswapPairTotalReservesSnapshot


class PairTotalReservesProcessor(CallbackAsyncWorker):
    _stream = None
    _snapshot_name = None
    _transformation_lambdas = None

    def __init__(self, name: str, **kwargs: dict) -> None:
        self._stream = 'uniswap_pairContract_pair_total_reserves'
        self._snapshot_name = 'pair reserves'
        self._transformation_lambdas = []
        super(PairTotalReservesProcessor, self).__init__(
            name=name,
            rmq_q=f'powerloom-backend-cb-{self._stream}:{settings.namespace}:{settings.instance_id}',
            rmq_routing=f'powerloom-backend-callback:{settings.namespace}:{settings.instance_id}.{self._stream}_worker',
            **kwargs,
        )

    async def _compute(
        self,
        min_chain_height: int,
        max_chain_height: int,
        data_source_contract_address: str,
    ) -> Optional[Dict[str, Union[int, float]]]:
        epoch_reserves_snapshot_map_token0 = dict()
        epoch_reserves_snapshot_map_token1 = dict()
        epoch_usd_reserves_snapshot_map_token0 = dict()
        epoch_usd_reserves_snapshot_map_token1 = dict()
        max_block_timestamp = int(time.time())

        try:
            # TODO: web3 object should be available within callback worker instance
            #  instead of being a global object in uniswap functions module. Not a good design pattern.
            pair_reserve_total = await get_pair_reserves(
                pair_address=data_source_contract_address,
                from_block=min_chain_height,
                to_block=max_chain_height,
                redis_conn=self._redis_conn,
                fetch_timestamp=True,
            )
        except Exception as exc:
            self._logger.opt(exception=True).error(
                (
                    'Pair-Reserves function failed for epoch:'
                    f' {min_chain_height}-{max_chain_height} | error_msg:{exc}'
                ),
            )
            # if querying fails, we are going to ensure it is recorded for future processing
            return None
        else:
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
                    'chainHeightRange': EpochBase(
                        begin=min_chain_height, end=max_chain_height,
                    ),
                    'timestamp': max_block_timestamp,
                    'contract': data_source_contract_address,
                },
            )
            return pair_total_reserves_snapshot
