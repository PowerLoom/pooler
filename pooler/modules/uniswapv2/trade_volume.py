import time

from .utils.core import get_pair_trade_volume
from pooler.settings.config import settings
from pooler.utils.callback_helpers import CallbackAsyncWorker
from pooler.utils.models.message_models import EpochBase
from pooler.utils.models.message_models import UniswapTradesSnapshot


class TradeVolumeProcessor(CallbackAsyncWorker):
    _stream = None
    _snapshot_name = None
    _transformation_lambdas = None

    def __init__(self, name: str, **kwargs: dict) -> None:
        self._stream = 'uniswap_pairContract_trade_volume'
        self._snapshot_name = 'trade volume and fees'
        self._transformation_lambdas = [
            self.transform_processed_epoch_to_trade_volume,
        ]
        super(TradeVolumeProcessor, self).__init__(
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
    ):
        self._logger.debug(f'trade volume {data_source_contract_address}, computation init time {time.time()}')
        result = await get_pair_trade_volume(
            data_source_contract_address=data_source_contract_address,
            min_chain_height=min_chain_height,
            max_chain_height=max_chain_height,
            redis_conn=self._redis_conn,
            rpc_helper=self._rpc_helper,
        )
        self._logger.debug(f'trade volume {data_source_contract_address}, computation end time {time.time()}')
        return result

    def transform_processed_epoch_to_trade_volume(
        self,
        trade_vol_processed_snapshot,
        data_source_contract_address,
        epoch_begin,
        epoch_end,
    ):
        self._logger.debug(
            'Trade volume processed snapshot: {}', trade_vol_processed_snapshot,
        )

        # Set effective trade volume at top level
        total_trades_in_usd = trade_vol_processed_snapshot['Trades'][
            'totalTradesUSD'
        ]
        total_fee_in_usd = trade_vol_processed_snapshot['Trades']['totalFeeUSD']
        total_token0_vol = trade_vol_processed_snapshot['Trades'][
            'token0TradeVolume'
        ]
        total_token1_vol = trade_vol_processed_snapshot['Trades'][
            'token1TradeVolume'
        ]
        total_token0_vol_usd = trade_vol_processed_snapshot['Trades'][
            'token0TradeVolumeUSD'
        ]
        total_token1_vol_usd = trade_vol_processed_snapshot['Trades'][
            'token1TradeVolumeUSD'
        ]

        max_block_timestamp = trade_vol_processed_snapshot.get('timestamp')
        trade_vol_processed_snapshot.pop('timestamp', None)
        trade_volume_snapshot = UniswapTradesSnapshot(
            **dict(
                contract=data_source_contract_address,
                chainHeightRange=EpochBase(begin=epoch_begin, end=epoch_end),
                timestamp=max_block_timestamp,
                totalTrade=float(f'{total_trades_in_usd: .6f}'),
                totalFee=float(f'{total_fee_in_usd: .6f}'),
                token0TradeVolume=float(f'{total_token0_vol: .6f}'),
                token1TradeVolume=float(f'{total_token1_vol: .6f}'),
                token0TradeVolumeUSD=float(f'{total_token0_vol_usd: .6f}'),
                token1TradeVolumeUSD=float(f'{total_token1_vol_usd: .6f}'),
                events=trade_vol_processed_snapshot,
            ),
        )
        return trade_volume_snapshot
