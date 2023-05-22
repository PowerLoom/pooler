from ipfs_client.main import AsyncIPFSClient
from redis import asyncio as aioredis

from ..utils.models.message_models import UniswapTradesAggregateSnapshot
from ..utils.models.message_models import UniswapTradesSnapshot
from pooler.utils.callback_helpers import GenericProcessorSingleProjectAggregate
from pooler.utils.data_utils import get_project_epoch_snapshot
from pooler.utils.data_utils import get_project_epoch_snapshot_bulk
from pooler.utils.data_utils import get_project_first_epoch
from pooler.utils.default_logger import logger
from pooler.utils.models.message_models import PowerloomSnapshotFinalizedMessage
from pooler.utils.rpc import RpcHelper


class AggreagateTradeVolumeProcessor(GenericProcessorSingleProjectAggregate):

    def __init__(self) -> None:
        self._logger = logger.bind(module='AggregateTradeVolumeProcessor')
        self.time_duration_in_seconds = 24 * 60 * 60

    def _add_aggregate_snapshot(
        self,
        previous_aggregate_snapshot: UniswapTradesAggregateSnapshot,
        current_snapshot: UniswapTradesSnapshot,
        block_idx: int,
    ):

        previous_aggregate_snapshot.totalTrade += current_snapshot.totalTradesUSD[block_idx]
        previous_aggregate_snapshot.totalFee += current_snapshot.totalFeesUSD[block_idx]
        previous_aggregate_snapshot.token0TradeVolume += current_snapshot.token0TradeVolume[block_idx]
        previous_aggregate_snapshot.token1TradeVolume += current_snapshot.token1TradeVolume[block_idx]
        previous_aggregate_snapshot.token0TradeVolumeUSD += current_snapshot.token0TradeVolumeUSD[block_idx]
        previous_aggregate_snapshot.token1TradeVolumeUSD += current_snapshot.token1TradeVolumeUSD[block_idx]

        return previous_aggregate_snapshot

    def _subtract_aggregate_snapshot(
        self,
        previous_aggregate_snapshot: UniswapTradesAggregateSnapshot,
        current_snapshot: UniswapTradesSnapshot,
        block_idx: int,
    ):

        previous_aggregate_snapshot.totalTrade -= current_snapshot.totalTradesUSD[block_idx]
        previous_aggregate_snapshot.totalFee -= current_snapshot.totalFeesUSD[block_idx]
        previous_aggregate_snapshot.token0TradeVolume -= current_snapshot.token0TradeVolume[block_idx]
        previous_aggregate_snapshot.token1TradeVolume -= current_snapshot.token1TradeVolume[block_idx]
        previous_aggregate_snapshot.token0TradeVolumeUSD -= current_snapshot.token0TradeVolumeUSD[block_idx]
        previous_aggregate_snapshot.token1TradeVolumeUSD -= current_snapshot.token1TradeVolumeUSD[block_idx]

        return previous_aggregate_snapshot

    async def _build_snapshot_from_scratch(
        self,
        msg_obj: PowerloomSnapshotFinalizedMessage,
        redis: aioredis.Redis,
        rpc_helper: RpcHelper,
        anchor_rpc_helper: RpcHelper,
        ipfs_reader: AsyncIPFSClient,
        protocol_state_contract,
        project_id: str,
    ):
        self._logger.info('project_first_epoch is 0, building aggregate from scratch')

        # using current snapshot for metadata
        current_snapshot_data = await get_project_epoch_snapshot(
            redis, protocol_state_contract, anchor_rpc_helper, ipfs_reader, msg_obj.epochId, msg_obj.projectId,
        )

        if not current_snapshot_data:
            self._logger.error(
                '24h Trade Volume snapshot building failed, snapshot for project {} and epoch {} not found',
                msg_obj.projectId, msg_obj.epochId,
            )
            return

        current_snapshot = UniswapTradesSnapshot.parse_raw(current_snapshot_data)

        # taking end timestamp from underlying snapshot
        end_timestamp = current_snapshot.blocks[-1].values()[0]

        begin_timestamp = end_timestamp - self.time_duration_in_seconds

        snapshot_complete = False

        # creating aggregate snapshot
        aggregate_snapshot = UniswapTradesAggregateSnapshot.parse_obj(
            {
                'epochId': msg_obj.epochId,
                'tailEpochId': msg_obj.epochId,
                'tailEpochIdBlockMarker': current_snapshot.blocks[-1].keys()[0],
            },
        )

        # source project first epoch
        source_project_first_epoch = await get_project_first_epoch(
            redis, protocol_state_contract, anchor_rpc_helper, msg_obj.projectId,
        )

        cur_epoch = msg_obj.epochId
        batch_size = 10

        while not snapshot_complete:
            if cur_epoch < source_project_first_epoch:
                break

            # while not snapshot_complete and
            snapshots_data = await get_project_epoch_snapshot_bulk(
                redis, protocol_state_contract, anchor_rpc_helper, ipfs_reader,
                cur_epoch - batch_size, cur_epoch, msg_obj.projectId,
            )

            # going in reverse order because we're expanding backwards
            for snapshot_data in snapshots_data[::-1]:
                if snapshot_data:
                    snapshot = UniswapTradesSnapshot.parse_raw(snapshot_data)

                    for i in range(len(snapshot.blocks) - 1, -1, -1):
                        if snapshot.blocks[i].values()[0] > begin_timestamp:
                            aggregate_snapshot = self._add_aggregate_snapshot(aggregate_snapshot, snapshot, i)
                            aggregate_snapshot.tailEpochId = snapshot.epochId
                            aggregate_snapshot.tailEpochIdBlockMarker = snapshot.blocks[i].keys()[0]
                            aggregate_snapshot.tailEpochIdBlockMarkerTimestamp = snapshot.blocks[i].values()[0]
                        else:
                            snapshot_complete = True
                            break

            cur_epoch = cur_epoch - batch_size

        return aggregate_snapshot

    async def compute(
        self,
        msg_obj: PowerloomSnapshotFinalizedMessage,
        redis: aioredis.Redis,
        rpc_helper: RpcHelper,
        anchor_rpc_helper: RpcHelper,
        ipfs_reader: AsyncIPFSClient,
        protocol_state_contract,
        project_id: str,

    ):
        self._logger.info(f'Building trade volume aggregate snapshot for {msg_obj}')

        # aggregate project first epoch
        project_first_epoch = await get_project_first_epoch(
            redis, protocol_state_contract, anchor_rpc_helper, project_id,
        )

        # If no past snapshots exist, then aggregate will be current snapshot
        if project_first_epoch == 0:
            return await self._build_snapshot_from_scratch(
                msg_obj, redis, rpc_helper, anchor_rpc_helper,
                ipfs_reader, protocol_state_contract, project_id,
            )

        else:
            self._logger.info('project_first_epoch is not 0, building aggregate from previous aggregate')

            # fetching any previous snapshot we can find to build from there
            prev_epoch_id = msg_obj.epochId - 1
            while True:
                previous_aggregate_snapshot_data = await get_project_epoch_snapshot(
                    redis, protocol_state_contract, anchor_rpc_helper,
                    ipfs_reader, msg_obj.epochId - 1, project_id,
                )

                if previous_aggregate_snapshot_data:
                    previous_aggregate_snapshot = UniswapTradesAggregateSnapshot.parse_raw(
                        previous_aggregate_snapshot_data,
                    )
                    break

                else:
                    prev_epoch_id = prev_epoch_id - 1

                    if prev_epoch_id < project_first_epoch:
                        self._logger.info('No previous aggregate snapshot found, building from scratch')
                        return await self._build_snapshot_from_scratch(
                            msg_obj, redis, rpc_helper, anchor_rpc_helper,
                            ipfs_reader, protocol_state_contract, project_id,
                        )

                # processing previous aggregate snapshot to generate new one
                current_snapshot_data = await get_project_epoch_snapshot(
                    redis, protocol_state_contract, anchor_rpc_helper,
                    ipfs_reader, msg_obj.epochId, msg_obj.projectId,
                )

                if not current_snapshot_data:
                    self._logger.error(
                        '24h Trade Volume snapshot building failed, snapshot for project {} and epoch {} not found',
                        msg_obj.projectId, msg_obj.epochId,
                    )
                    return

                current_snapshot = UniswapTradesSnapshot.parse_raw(current_snapshot_data)

                # taking end timestamp from underlying snapshot
                end_timestamp = current_snapshot.blocks[-1].values()[0]

                begin_timestamp = end_timestamp - self.time_duration_in_seconds

                # Add all new missing snapshots to the aggregate
                snapshots_data = await get_project_epoch_snapshot_bulk(
                    redis, protocol_state_contract, anchor_rpc_helper, ipfs_reader,
                    prev_epoch_id + 1, msg_obj.epochId, msg_obj.projectId,
                )

                for snapshot_data in snapshots_data:
                    if snapshot_data:
                        snapshot = UniswapTradesSnapshot.parse_raw(snapshot_data)

                        for i in range(len(snapshot.blocks) - 1, -1, -1):
                            aggregate_snapshot = self._add_aggregate_snapshot(aggregate_snapshot, snapshot, i)

                # remove all snapshots that are outside of the time window
                tail_cleaned = False
                tail_cursor = aggregate_snapshot.tailEpochId
                tail_cursor_block_marker = aggregate_snapshot.tailEpochIdBlockMarker
                tail_epoch_id_block_marker_timestamp = aggregate_snapshot.tailEpochIdBlockMarkerTimestamp

                # if snapshot window > 24h, then we need to remove snapshots that are outside of the window
                if tail_epoch_id_block_marker_timestamp < begin_timestamp:

                    while not tail_cleaned:
                        tail_snapshot_data = await get_project_epoch_snapshot(
                            redis, protocol_state_contract, anchor_rpc_helper,
                            ipfs_reader, tail_cursor, msg_obj.projectId,
                        )

                        if not tail_snapshot_data:
                            tail_cursor_block_marker = None
                            tail_cursor += 1
                            continue

                        tail_snapshot = UniswapTradesSnapshot.parse_raw(tail_snapshot_data)

                        sub = False
                        for i in range(len(tail_snapshot.blocks) - 1, -1, -1):
                            if tail_cursor_block_marker and \
                                    tail_snapshot.blocks[i].keys()[0] == tail_cursor_block_marker:
                                sub = True
                                tail_cursor_block_marker = None

                            if not tail_cursor_block_marker:
                                sub = True

                            if sub:

                                if tail_snapshot.blocks[i].values()[0] < begin_timestamp:

                                    aggregate_snapshot = self._subtract_aggregate_snapshot(
                                        aggregate_snapshot, tail_snapshot, i,
                                    )
                                    aggregate_snapshot.tailEpochId = tail_snapshot.epochId
                                    aggregate_snapshot.tailEpochIdBlockMarker = tail_snapshot.blocks[i].keys()[0]
                                    aggregate_snapshot.tailEpochIdBlockMarkerTimestamp = (
                                        tail_snapshot.blocks[i].values()[0]
                                    )
                                else:
                                    tail_cleaned = True
                                    break

                        tail_cursor += 1

        return aggregate_snapshot
