import time
from typing import Dict
from typing import Optional
from typing import Union

from redis import asyncio as aioredis

from .utils.core import get_pair_reserves
from .utils.models.message_models import UniswapPairTotalReservesSnapshot
from pooler.utils.callback_helpers import GenericProcessorSnapshot
from pooler.utils.default_logger import logger
from pooler.utils.models.message_models import PowerloomSnapshotProcessMessage
from pooler.utils.rpc import RpcHelper


class PairTotalReservesProcessor(GenericProcessorSnapshot):

    def __init__(self) -> None:
        self._logger = logger.bind(module='PairTotalReservesProcessor')

    async def compute(
        self,
        msg_obj: PowerloomSnapshotProcessMessage,
        redis_conn: aioredis.Redis,
        rpc_helper: RpcHelper,

    ) -> Optional[Dict[str, Union[int, float]]]:

        data_source_contract_address = msg_obj.contract
        min_chain_height = msg_obj.begin
        max_chain_height = msg_obj.end

        self._logger.debug(f'pair reserves {data_source_contract_address} computation init time {time.time()}')
        pair_reserve_total = await get_pair_reserves(
            pair_address=data_source_contract_address,
            from_block=min_chain_height,
            to_block=max_chain_height,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
            fetch_timestamp=True,
        )

        snapshot = UniswapPairTotalReservesSnapshot(
            **{
                'blocks': [],
                'epochId': msg_obj.epochId,
                'contract': msg_obj.contract,
                'token0Prices': [],
                'token0Reserves': [],
                'token0ReservesUSD': [],
                'token1Prices': [],
                'token1Reserves': [],
                'token1ReservesUSD': [],
            },
        )

        for block_num, block_data in pair_reserve_total.values():
            snapshot.blocks.append({
                str(block_num): block_data['timestamp'],
            })

            snapshot.token0Prices.append(block_data['token0Price'])
            snapshot.token0Reserves.append(block_data['token0'])
            snapshot.token0ReservesUSD.append(block_data['token0USD'])

            snapshot.token1Prices.append(block_data['token1Price'])
            snapshot.token1Reserves.append(block_data['token1'])
            snapshot.token1ReservesUSD.append(block_data['token1USD'])

        self._logger.debug(f'pair reserves {data_source_contract_address}, computation end time {time.time()}')

        return snapshot
