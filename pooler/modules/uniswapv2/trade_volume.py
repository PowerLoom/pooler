import time

from poooler.utils.model.message_models import PowerloomSnapshotProcessMessage
from redis import asyncio as aioredis

from .utils.core import get_pair_trade_volume
from .utils.models.message_models import UniswapTradesSnapshot
from pooler.utils.callback_helpers import GenericProcessorSnapshot
from pooler.utils.default_logger import logger
from pooler.utils.rpc import RpcHelper


class TradeVolumeProcessor(GenericProcessorSnapshot):

    def __init__(self) -> None:
        self._logger = logger.bind(module='TradeVolumeProcessor')

    async def compute(
        self,
        msg_obj: PowerloomSnapshotProcessMessage,
        redis_conn: aioredis.Redis,
        rpc_helper: RpcHelper,
    ):

        data_source_contract_address = msg_obj.contract
        min_chain_height = msg_obj.begin
        max_chain_height = msg_obj.end

        self._logger.debug(f'trade volume {data_source_contract_address}, computation init time {time.time()}')
        trade_volume_data = await get_pair_trade_volume(
            data_source_contract_address=data_source_contract_address,
            min_chain_height=min_chain_height,
            max_chain_height=max_chain_height,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
        )

        snapshot = UniswapTradesSnapshot(
            **{
                'blocks': [],
                'epochId': msg_obj.epochId,
                'contract': msg_obj.contract,
                'totalTradesUSD': [],
                'totalFeesUSD': [],
                'token0TradeVolumes': [],
                'token1TradeVolumes': [],
                'token0TradeVolumesUSD': [],
                'token1TradeVolumesUSD': [],
                'events': [],
            },
        )

        for block_num, block_data in trade_volume_data.values():
            snapshot.blocks.append({
                str(block_num): block_data['timestamp'],
            })

            snapshot.totalTradesUSD.append(
                block_data['trades'].totalTradesUSD,
            )

            snapshot.totalFeesUSD.append(
                block_data['trades'].totalFeeUSD,
            )

            snapshot.token0TradeVolumes.append(
                block_data['trades'].token0TradeVolume,
            )

            snapshot.token1TradeVolumes.append(
                block_data['trades'].token1TradeVolume,
            )

            snapshot.token0TradeVolumesUSD.append(
                block_data['trades'].token0TradeVolumeUSD,
            )

            snapshot.token1TradeVolumesUSD.append(
                block_data['trades'].token1TradeVolumeUSD,
            )

            snapshot.events.append(
                block_data['eventLogs'],
            )

        self._logger.debug(f'trade volume {data_source_contract_address}, computation end time {time.time()}')

        return snapshot
