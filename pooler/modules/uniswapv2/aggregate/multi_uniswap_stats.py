from redis import asyncio as aioredis

from pooler.utils.callback_helpers import GenericProcessorMultiProjectAggregate
from pooler.utils.default_logger import logger
from pooler.utils.models.message_models import PowerloomCalculateAggregateMessage
from pooler.utils.rpc import RpcHelper


class AggreagateStatsProcessor(GenericProcessorMultiProjectAggregate):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
        self._logger = logger.bind(module='AggregateStatsProcessor')

    async def compute(
        self,
        msg_obj: PowerloomCalculateAggregateMessage,
        redis: aioredis.Redis,
        rpc_helper: RpcHelper,
        anchor_rpc_helper: RpcHelper,
        protocol_state_contract,
        project_id: str,

    ):
        self._logger.info(f'compute called with {msg_obj}')
