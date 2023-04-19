from redis import asyncio as aioredis

from pooler.utils.callback_helpers import GenericProcessorAggregateBasedAggregate
from pooler.utils.default_logger import logger
from pooler.utils.models.message_models import PowerloomAggregateFinalizedMessage
from pooler.utils.rpc import RpcHelper


class AggreagateStatsProcessor(GenericProcessorAggregateBasedAggregate):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
        self._logger = logger.bind(module='AggregateStatsProcessor')

    async def compute(
        self,
        msg_obj: PowerloomAggregateFinalizedMessage,
        redis: aioredis,
        rpc_helper: RpcHelper,
    ):
        self._logger.info(f'compute called with {msg_obj}')
