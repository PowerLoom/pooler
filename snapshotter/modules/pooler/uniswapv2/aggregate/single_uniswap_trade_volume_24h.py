import asyncio
import json

from ipfs_client.main import AsyncIPFSClient
from redis import asyncio as aioredis

from ..utils.models.message_models import UniswapTradesAggregateSnapshot
from ..utils.models.message_models import UniswapTradesSnapshot
from snapshotter.utils.callback_helpers import GenericProcessorAggregate
from snapshotter.utils.data_utils import get_project_epoch_snapshot_bulk
from snapshotter.utils.data_utils import get_project_first_epoch
from snapshotter.utils.data_utils import get_submission_data
from snapshotter.utils.data_utils import get_tail_epoch_id
from snapshotter.utils.default_logger import logger
from snapshotter.utils.models.message_models import PowerloomSnapshotSubmittedMessage
from snapshotter.utils.redis.redis_keys import project_finalized_data_zset
from snapshotter.utils.redis.redis_keys import submitted_base_snapshots_key
from snapshotter.utils.rpc import RpcHelper


class AggreagateTradeVolumeProcessor(GenericProcessorAggregate):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
        self._logger = logger.bind(module='AggregateTradeVolumeProcessor24h')

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

    async def _calculate_from_scratch(
        self,
        msg_obj: PowerloomSnapshotSubmittedMessage,
        redis: aioredis.Redis,
        rpc_helper: RpcHelper,
        anchor_rpc_helper: RpcHelper,
        ipfs_reader: AsyncIPFSClient,
        protocol_state_contract,
        project_id: str,
    ):
        calculate_from_scratch_in_progress = await redis.get(f'calculate_from_scratch:{project_id}')
        if calculate_from_scratch_in_progress:
            self._logger.info('calculate_from_scratch already in progress, skipping')
            return

        self._logger.info('building aggregate from scratch')
        await redis.set(
            name=f'calculate_from_scratch:{project_id}',
            value='true',
            ex=300,
        )
        # source project tail epoch
        tail_epoch_id, extrapolated_flag = await get_tail_epoch_id(
            redis, protocol_state_contract, anchor_rpc_helper, msg_obj.epochId, 86400, msg_obj.projectId,
        )

        # for the first epoch, using submitted cid
        current_epoch_underlying_data = await get_submission_data(
            redis, msg_obj.snapshotCid, ipfs_reader, project_id,
        )

        snapshots_data = await get_project_epoch_snapshot_bulk(
            redis, protocol_state_contract, anchor_rpc_helper, ipfs_reader,
            tail_epoch_id, msg_obj.epochId - 1, msg_obj.projectId,
        )

        aggregate_snapshot = UniswapTradesAggregateSnapshot.parse_obj({'epochId': msg_obj.epochId})
        if extrapolated_flag:
            aggregate_snapshot.complete = False
        if current_epoch_underlying_data:
            current_snapshot = UniswapTradesSnapshot.parse_obj(current_epoch_underlying_data)
            aggregate_snapshot = self._add_aggregate_snapshot(aggregate_snapshot, current_snapshot)

        for snapshot_data in snapshots_data:
            if snapshot_data:
                snapshot = UniswapTradesSnapshot.parse_obj(snapshot_data)
                aggregate_snapshot = self._add_aggregate_snapshot(aggregate_snapshot, snapshot)

        await redis.delete(f'calculate_from_scratch:{project_id}')

        return aggregate_snapshot

    async def compute(
        self,
        msg_obj: PowerloomSnapshotSubmittedMessage,
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
            return await self._calculate_from_scratch(
                msg_obj, redis, rpc_helper, anchor_rpc_helper, ipfs_reader, protocol_state_contract, project_id,
            )

        else:
            self._logger.info('project_first_epoch is not 0, building aggregate from previous aggregate')

            # get key with highest score
            project_last_finalized = await redis.zrevrangebyscore(
                project_finalized_data_zset(project_id),
                max='+inf',
                min='-inf',
                withscores=True,
                start=0,
                num=1,
            )

            if project_last_finalized:
                project_last_finalized_cid, project_last_finalized_epoch = project_last_finalized[0]
                project_last_finalized_epoch = int(project_last_finalized_epoch)
                project_last_finalized_cid = project_last_finalized_cid.decode('utf-8')
            else:
                self._logger.info('project_last_finalized is None, trying to fetch from contract')
                return await self._calculate_from_scratch(
                    msg_obj, redis, rpc_helper, anchor_rpc_helper, ipfs_reader, protocol_state_contract, project_id,
                )

            tail_epoch_id, extrapolated_flag = await get_tail_epoch_id(
                redis, protocol_state_contract, anchor_rpc_helper, msg_obj.epochId, 86400, msg_obj.projectId,
            )

            if extrapolated_flag:
                aggregate_complete_flag = False
            else:
                aggregate_complete_flag = True

            if project_last_finalized_epoch <= tail_epoch_id:
                self._logger.error('last finalized epoch is too old, building aggregate from scratch')
                return await self._calculate_from_scratch(
                    msg_obj, redis, rpc_helper, anchor_rpc_helper, ipfs_reader, protocol_state_contract, project_id,
                )

            project_last_finalized_data = await get_submission_data(
                redis, project_last_finalized_cid, ipfs_reader, project_id,
            )

            if not project_last_finalized_data:
                self._logger.info('project_last_finalized_data is None, building aggregate from scratch')
                return await self._calculate_from_scratch(
                    msg_obj, redis, rpc_helper, anchor_rpc_helper, ipfs_reader, protocol_state_contract, project_id,
                )

            aggregate_snapshot = UniswapTradesAggregateSnapshot.parse_obj(project_last_finalized_data)
            # updating epochId to current epoch
            aggregate_snapshot.epochId = msg_obj.epochId

            base_project_last_finalized = await redis.zrevrangebyscore(
                project_finalized_data_zset(msg_obj.projectId),
                max='+inf',
                min='-inf',
                withscores=True,
                start=0,
                num=1,
            )

            if base_project_last_finalized:
                _, base_project_last_finalized_epoch_ = base_project_last_finalized[0]
                base_project_last_finalized_epoch = int(base_project_last_finalized_epoch_)
            else:
                base_project_last_finalized_epoch = 0

            if base_project_last_finalized_epoch and project_last_finalized_epoch < base_project_last_finalized_epoch:
                # fetch base finalized snapshots if they exist and are within 5 epochs of current epoch
                base_finalized_snapshot_range = (
                    project_last_finalized_epoch + 1,
                    base_project_last_finalized_epoch,
                )

                base_finalized_snapshots = await get_project_epoch_snapshot_bulk(
                    redis, protocol_state_contract, anchor_rpc_helper, ipfs_reader,
                    base_finalized_snapshot_range[0], base_finalized_snapshot_range[1], msg_obj.projectId,
                )
            else:
                base_finalized_snapshots = []
                base_finalized_snapshot_range = (0, project_last_finalized_epoch)

            base_unfinalized_tasks = []
            for epoch_id in range(base_finalized_snapshot_range[1] + 1, msg_obj.epochId + 1):
                base_unfinalized_tasks.append(
                    redis.get(submitted_base_snapshots_key(epoch_id=epoch_id, project_id=msg_obj.projectId)),
                )

            base_unfinalized_snapshots_raw = await asyncio.gather(*base_unfinalized_tasks, return_exceptions=True)

            base_unfinalized_snapshots = []
            for snapshot_data in base_unfinalized_snapshots_raw:
                # check if not exception and not None
                if not isinstance(snapshot_data, Exception) and snapshot_data:
                    base_unfinalized_snapshots.append(
                        json.loads(snapshot_data),
                    )
                else:
                    self._logger.error(
                        f'Error fetching base unfinalized snapshot, cancelling aggregation for epoch {msg_obj.epochId}',
                    )
                    return None

            base_snapshots = base_finalized_snapshots + base_unfinalized_snapshots

            for snapshot_data in base_snapshots:
                if snapshot_data:
                    snapshot = UniswapTradesSnapshot.parse_obj(snapshot_data)
                    aggregate_snapshot = self._add_aggregate_snapshot(aggregate_snapshot, snapshot)

            # Remove from tail if needed
            tail_epochs_to_remove = []
            for epoch_id in range(project_last_finalized_epoch, msg_obj.epochId):
                tail_epoch_id, extrapolated_flag = await get_tail_epoch_id(
                    redis, protocol_state_contract, anchor_rpc_helper, epoch_id, 86400, msg_obj.projectId,
                )
                if not extrapolated_flag:
                    tail_epochs_to_remove.append(tail_epoch_id)
            if tail_epochs_to_remove:
                tail_epoch_snapshots = await get_project_epoch_snapshot_bulk(
                    redis, protocol_state_contract, anchor_rpc_helper, ipfs_reader,
                    tail_epochs_to_remove[0], tail_epochs_to_remove[-1], msg_obj.projectId,
                )

                for snapshot_data in tail_epoch_snapshots:
                    if snapshot_data:
                        snapshot = UniswapTradesSnapshot.parse_obj(snapshot_data)
                        aggregate_snapshot = self._remove_aggregate_snapshot(aggregate_snapshot, snapshot)

            if aggregate_complete_flag:
                aggregate_snapshot.complete = True
            else:
                aggregate_snapshot.complete = False

            return aggregate_snapshot
