from redis import asyncio as aioredis

from ..utils.models.message_models import UniswapTradesAggregateSnapshot
from ..utils.models.message_models import UniswapTradesSnapshot
from pooler.utils.aggregation_helper import get_project_epoch_snapshot_bulk
from pooler.utils.aggregation_helper import get_project_first_epoch
from pooler.utils.aggregation_helper import get_tail_epoch_id
from pooler.utils.callback_helpers import GenericProcessorSingleProjectAggregate
from pooler.utils.default_logger import logger
from pooler.utils.models.message_models import PowerloomSnapshotFinalizedMessage
from pooler.utils.rpc import RpcHelper


class AggreagateTradeVolumeProcessor(GenericProcessorSingleProjectAggregate):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
        self._logger = logger.bind(module='AggregateTradeVolumeProcessor')

    def _add_aggregate_snapshot(
        self,
        previous_aggregate_snapshot: UniswapTradesAggregateSnapshot,
        current_snapshot: UniswapTradesSnapshot,
    ):

        previous_aggregate_snapshot.totalTrade += current_snapshot.totalTrade
        previous_aggregate_snapshot.totalFee += current_snapshot.totalFee
        previous_aggregate_snapshot.token0TradeVolume += current_snapshot.token0TradeVolume
        previous_aggregate_snapshot.token1TradeVolume += current_snapshot.token1TradeVolume
        previous_aggregate_snapshot.token0TradeVolumeUSD += current_snapshot.token0TradeVolumeUSD
        previous_aggregate_snapshot.token1TradeVolumeUSD += current_snapshot.token1TradeVolumeUSD

        return previous_aggregate_snapshot

    def _remove_aggregate_snapshot(
        self,
        previous_aggregate_snapshot: UniswapTradesAggregateSnapshot,
        current_snapshot: UniswapTradesSnapshot,
    ):

        previous_aggregate_snapshot.totalTrade -= current_snapshot.totalTrade
        previous_aggregate_snapshot.totalFee -= current_snapshot.totalFee
        previous_aggregate_snapshot.token0TradeVolume -= current_snapshot.token0TradeVolume
        previous_aggregate_snapshot.token1TradeVolume -= current_snapshot.token1TradeVolume
        previous_aggregate_snapshot.token0TradeVolumeUSD -= current_snapshot.token0TradeVolumeUSD
        previous_aggregate_snapshot.token1TradeVolumeUSD -= current_snapshot.token1TradeVolumeUSD

        return previous_aggregate_snapshot

    async def compute(
        self,
        msg_obj: PowerloomSnapshotFinalizedMessage,
        redis: aioredis.Redis,
        rpc_helper: RpcHelper,
        anchor_rpc_helper: RpcHelper,
        protocol_state_contract,
        project_id: str,

    ):
        self._logger.info(f'compute called with {msg_obj}')

        # aggregate project first epoch
        project_first_epoch = await get_project_first_epoch(
            redis, protocol_state_contract, anchor_rpc_helper, project_id,
        )

        # source project tail epoch
        [tail_epoch_id, complete] = await get_tail_epoch_id(
            redis, protocol_state_contract, anchor_rpc_helper, msg_obj.epochId, 86400, msg_obj.projectId,
        )

        # If no past snapshots exist, then aggregate will be current snapshot
        if project_first_epoch == 0:
            snapshots_data = await get_project_epoch_snapshot_bulk(
                redis, protocol_state_contract, anchor_rpc_helper, range(
                    tail_epoch_id, msg_obj.epochId + 1,
                ), msg_obj.projectId,
            )

            aggregate_snapshot = UniswapTradesAggregateSnapshot.parse_obj({})

            for snapshot_data in snapshots_data:
                if snapshot_data:
                    snapshot = UniswapTradesSnapshot.parse_raw(snapshot_data)
                    aggregate_snapshot = self._add_aggregate_snapshot(aggregate_snapshot, snapshot)

        else:
            # if epoch window is not complete, just add current snapshot to the aggregate
            [previous_aggregate_snapshot_data] = await get_project_epoch_snapshot_bulk(
                redis, protocol_state_contract, anchor_rpc_helper, [msg_obj.epochId - 1], project_id,
            )

            if previous_aggregate_snapshot_data:
                aggregate_snapshot = UniswapTradesAggregateSnapshot.parse_raw(previous_aggregate_snapshot_data)

                [current_snapshot_data] = await get_project_epoch_snapshot_bulk(
                    redis, protocol_state_contract, anchor_rpc_helper, [msg_obj.epochId], msg_obj.projectId,
                )

                current_snapshot = UniswapTradesSnapshot.parse_raw(current_snapshot_data)

                if complete:
                    [current_tail_end_snapshot_data] = await get_project_epoch_snapshot_bulk(
                        redis, protocol_state_contract, anchor_rpc_helper, [tail_epoch_id], project_id,
                    )

                    current_tail_end_snapshot = UniswapTradesSnapshot.parse_raw(current_tail_end_snapshot_data)

                    aggregate_snapshot = self._remove_aggregate_snapshot(
                        aggregate_snapshot, current_tail_end_snapshot,
                    )

                aggregate_snapshot = self._add_aggregate_snapshot(aggregate_snapshot, current_snapshot)

            else:
                # if previous_aggregate_snapshot_data is not found for some reason, do entire calculation
                snapshots_data = await get_project_epoch_snapshot_bulk(
                    redis, protocol_state_contract, anchor_rpc_helper, range(
                        tail_epoch_id, msg_obj.epochId + 1,
                    ), msg_obj.projectId,
                )

                aggregate_snapshot = UniswapTradesAggregateSnapshot.parse_obj({})

                for snapshot_data in snapshots_data:
                    if snapshot_data:
                        snapshot = UniswapTradesSnapshot.parse_raw(snapshot_data)
                        aggregate_snapshot = self._add_aggregate_snapshot(aggregate_snapshot, snapshot)

            return aggregate_snapshot
