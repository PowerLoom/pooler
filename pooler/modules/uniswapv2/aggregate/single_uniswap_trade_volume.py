from redis import asyncio as aioredis

from ..utils.models.message_models import UniswapTradesSnapshot
from pooler.utils.aggregation_helper import get_project_epoch_snapshot
from pooler.utils.callback_helpers import GenericProcessorSingleProjectAggregate
from pooler.utils.default_logger import logger
from pooler.utils.models.message_models import PowerloomSnapshotFinalizedMessage
from pooler.utils.rpc import RpcHelper


class AggreagateTradeVolumeProcessor(GenericProcessorSingleProjectAggregate):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
        self._logger = logger.bind(module='AggregateTradeVolumeProcessor')

    async def compute(
        self,
        msg_obj: PowerloomSnapshotFinalizedMessage,
        redis: aioredis,
        rpc_helper: RpcHelper,
        anchor_rpc_helper: RpcHelper,
        protocol_state_contract,

    ):
        self._logger.info(f'compute called with {msg_obj}')
        # Get the submission data
        submission_data = await get_project_epoch_snapshot(
            redis, protocol_state_contract, anchor_rpc_helper, msg_obj.epochId, msg_obj.projectId,
        )
        if submission_data:
            trade_volume_snapshot = UniswapTradesSnapshot.parse_raw(submission_data)

            self._logger.info('Trade Volume Snapshot {}', trade_volume_snapshot)
