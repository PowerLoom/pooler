from redis import asyncio as aioredis

from pooler.utils.callback_helpers import GenericProcessorIndexBasedAggregate
from pooler.utils.default_logger import logger
from pooler.utils.models.message_models import PowerloomIndexFinalizedMessage
from pooler.utils.rpc import RpcHelper


class AggreagatePairReserveProcessor(GenericProcessorIndexBasedAggregate):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
        self._logger = logger.bind(module='AggregatePairReserveProcessor')

    async def compute(
        self,
        msg_obj: PowerloomIndexFinalizedMessage,
        redis: aioredis,
        rpc_helper: RpcHelper,
    ):
        self._logger.info(f'compute called with {msg_obj}')
