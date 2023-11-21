import time
from typing import Dict
from typing import Optional
from typing import Union

from redis import asyncio as aioredis

from .utils.core import get_pair_reserves
from .utils.models.message_models import UniswapPairTotalReservesSnapshot
from pooler.utils.callback_helpers import GenericProcessorSnapshot
from pooler.utils.default_logger import logger
from pooler.utils.models.message_models import EpochBaseSnapshot
from pooler.utils.rpc import RpcHelper


class LiquidityDepth(GenericProcessorSnapshot):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
        self._logger = logger.bind(module="PairTotalReservesProcessor")

    async def compute(
        self,
        min_chain_height: int,
        max_chain_height: int,
        data_source_contract_address: str,
        redis_conn: aioredis.Redis,
        rpc_helper: RpcHelper,
    ) -> Optional[Dict[str, Union[int, float]]]:


        self._logger.debug(
            f"pair reserves {data_source_contract_address} computation init time {time.time()}"
        )

        liquidity_depth_snapshot = await get_liquidity_depth(
            pair_address=data_source_contract_address,
            from_block=min_chain_height,
            to_block=max_chain_height,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
            fetch_timestamp=True,
        )

        for block_num in range(min_chain_height, max_chain_height + 1):
            print()
        self._logger.debug(
            f"pair reserves {data_source_contract_address}, computation end time {time.time()}"
        )

        return pair_total_reserves_snapshot
