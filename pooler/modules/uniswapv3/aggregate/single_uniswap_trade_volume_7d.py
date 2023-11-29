import asyncio

import pydantic
from ipfs_client.main import AsyncIPFSClient
from redis import asyncio as aioredis

from ..utils.models.message_models import UniswapTradesAggregateSnapshot
from pooler.modules.uniswapv3.utils.helpers import get_pair_metadata
from pooler.utils.callback_helpers import GenericProcessorSingleProjectAggregate
from pooler.utils.data_utils import get_project_epoch_snapshot
from pooler.utils.data_utils import get_submission_data
from pooler.utils.data_utils import get_tail_epoch_id
from pooler.utils.default_logger import logger
from pooler.utils.models.message_models import PowerloomSnapshotSubmittedMessage
from pooler.utils.rpc import RpcHelper


class AggregateTradeVolumeProcessor(GenericProcessorSingleProjectAggregate):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
        self._logger = logger.bind(module="AggregateTradeVolumeProcessor7d")

    def _add_aggregate_snapshot(
        self,
        previous_aggregate_snapshot: UniswapTradesAggregateSnapshot,
        current_snapshot: UniswapTradesAggregateSnapshot,
    ):
        previous_aggregate_snapshot.totalTrade += current_snapshot.totalTrade
        previous_aggregate_snapshot.totalFee += current_snapshot.totalFee
        previous_aggregate_snapshot.token0TradeVolume += (
            current_snapshot.token0TradeVolume
        )
        previous_aggregate_snapshot.token1TradeVolume += (
            current_snapshot.token1TradeVolume
        )
        previous_aggregate_snapshot.token0TradeVolumeUSD += (
            current_snapshot.token0TradeVolumeUSD
        )
        previous_aggregate_snapshot.token1TradeVolumeUSD += (
            current_snapshot.token1TradeVolumeUSD
        )

        return previous_aggregate_snapshot

    def _remove_aggregate_snapshot(
        self,
        previous_aggregate_snapshot: UniswapTradesAggregateSnapshot,
        current_snapshot: UniswapTradesAggregateSnapshot,
    ):
        previous_aggregate_snapshot.totalTrade -= current_snapshot.totalTrade
        previous_aggregate_snapshot.totalFee -= current_snapshot.totalFee
        previous_aggregate_snapshot.token0TradeVolume -= (
            current_snapshot.token0TradeVolume
        )
        previous_aggregate_snapshot.token1TradeVolume -= (
            current_snapshot.token1TradeVolume
        )
        previous_aggregate_snapshot.token0TradeVolumeUSD -= (
            current_snapshot.token0TradeVolumeUSD
        )
        previous_aggregate_snapshot.token1TradeVolumeUSD -= (
            current_snapshot.token1TradeVolumeUSD
        )

        return previous_aggregate_snapshot

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
        self._logger.info(
            f"Building 7 day trade volume aggregate snapshot against {msg_obj}"
        )

        contract = project_id.split(":")[-2]

        pair_metadata = await get_pair_metadata(
            pair_address=contract,
            redis_conn=redis,
            rpc_helper=rpc_helper,
        )
        aggregate_snapshot = UniswapTradesAggregateSnapshot(
            epochId=msg_obj.epochId,
        )
        # 24h snapshots fetches
        snapshot_tasks = list()
        self._logger.debug(
            "fetching 24hour aggregates spaced out by 1 day over 7 days..."
        )
        # 1. find one day tail epoch
        count = 0
        self._logger.debug(
            "fetch # {}: queueing task for 24h aggregate snapshot for project ID {}"
            " at currently received epoch ID {} with snasphot CID {}",
            count,
            msg_obj.projectId,
            msg_obj.epochId,
            msg_obj.snapshotCid,
        )

        snapshot_tasks.append(
            get_submission_data(
                redis,
                msg_obj.snapshotCid,
                ipfs_reader,
                msg_obj.projectId,
            ),
        )
        seek_stop_flag = False
        head_epoch = msg_obj.epochId
        # 2. if not extrapolated, attempt to seek further back
        while not seek_stop_flag or count < 7:
            tail_epoch_id, seek_stop_flag = await get_tail_epoch_id(
                redis,
                protocol_state_contract,
                anchor_rpc_helper,
                head_epoch,
                86400,
                msg_obj.projectId,
            )
            count += 1
            if not seek_stop_flag or count > 1:
                self._logger.debug(
                    "fetch # {}: for 7d aggregated trade volume calculations: "
                    "queueing task for 24h aggregate snapshot for project ID {} at rewinded epoch ID {}",
                    count,
                    msg_obj.projectId,
                    tail_epoch_id,
                )
                snapshot_tasks.append(
                    get_project_epoch_snapshot(
                        redis,
                        protocol_state_contract,
                        anchor_rpc_helper,
                        ipfs_reader,
                        tail_epoch_id,
                        msg_obj.projectId,
                    ),
                )
            head_epoch = tail_epoch_id - 1
        if count == 7:
            self._logger.info(
                "fetch # {}: reached 7 day limit for 24h aggregate snapshots for project ID {} at rewinded epoch ID {}",
                count,
                msg_obj.projectId,
                tail_epoch_id,
            )
        all_snapshots = await asyncio.gather(*snapshot_tasks, return_exceptions=True)
        self._logger.debug(
            "for 7d aggregated trade volume calculations: fetched {} "
            "24h aggregated trade volume snapshots for project ID {}: {}",
            len(all_snapshots),
            msg_obj.projectId,
            all_snapshots,
        )
        for single_24h_snapshot in all_snapshots:
            if not isinstance(single_24h_snapshot, BaseException):
                try:
                    snapshot = UniswapTradesAggregateSnapshot.parse_obj(
                        single_24h_snapshot
                    )
                except pydantic.ValidationError:
                    pass
                else:
                    aggregate_snapshot = self._add_aggregate_snapshot(
                        aggregate_snapshot, snapshot
                    )
        return aggregate_snapshot
