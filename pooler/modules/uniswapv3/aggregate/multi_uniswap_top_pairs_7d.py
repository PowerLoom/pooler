from ipfs_client.main import AsyncIPFSClient
from redis import asyncio as aioredis

from ..utils.helpers import get_pair_metadata
from ..utils.models.message_models import UniswapTopPair7dSnapshot
from ..utils.models.message_models import UniswapTopPairs7dSnapshot
from ..utils.models.message_models import UniswapTradesAggregateSnapshot
from pooler.utils.callback_helpers import GenericProcessorMultiProjectAggregate
from pooler.utils.data_utils import get_sumbmission_data_bulk
from pooler.utils.default_logger import logger
from pooler.utils.models.message_models import PowerloomCalculateAggregateMessage
from pooler.utils.rpc import RpcHelper


class AggregateTopPairsProcessor(GenericProcessorMultiProjectAggregate):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
        self._logger = logger.bind(module="AggregateTopPairsProcessor")

    async def compute(
        self,
        msg_obj: PowerloomCalculateAggregateMessage,
        redis: aioredis.Redis,
        rpc_helper: RpcHelper,
        anchor_rpc_helper: RpcHelper,
        ipfs_reader: AsyncIPFSClient,
        protocol_state_contract,
        project_id: str,
    ):
        self._logger.info(f"Calculating 7d top pairs trade volume data for {msg_obj}")

        epoch_id = msg_obj.epochId

        snapshot_mapping = {}
        all_pair_metadata = {}

        snapshot_data = await get_sumbmission_data_bulk(
            redis,
            [msg.snapshotCid for msg in msg_obj.messages],
            ipfs_reader,
            [msg.projectId for msg in msg_obj.messages],
        )

        for msg, data in zip(msg_obj.messages, snapshot_data):
            if not data:
                continue
            snapshot = UniswapTradesAggregateSnapshot.parse_obj(data)
            snapshot_mapping[msg.projectId] = snapshot

            contract_address = msg.projectId.split(":")[-2]
            if contract_address not in all_pair_metadata:
                pair_metadata = await get_pair_metadata(
                    contract_address,
                    redis_conn=redis,
                    rpc_helper=rpc_helper,
                )

                all_pair_metadata[contract_address] = pair_metadata

        # iterate over all snapshots and generate pair data
        pair_data = {}
        for snapshot_project_id in snapshot_mapping.keys():
            snapshot = snapshot_mapping[snapshot_project_id]
            contract = snapshot_project_id.split(":")[-2]
            pair_metadata = all_pair_metadata[contract]

            if contract not in pair_data:
                pair_data[contract] = {
                    "address": contract,
                    "name": pair_metadata["pair"]["symbol"],
                    "volume7d": 0,
                    "fee7d": 0,
                }

            pair_data[contract]["volume7d"] += snapshot.totalTrade
            pair_data[contract]["fee7d"] += snapshot.totalFee

        top_pairs = []
        for pair in pair_data.values():
            top_pairs.append(UniswapTopPair7dSnapshot.parse_obj(pair))

        top_pairs = sorted(top_pairs, key=lambda x: x.volume7d, reverse=True)

        top_pairs_snapshot = UniswapTopPairs7dSnapshot(
            epochId=epoch_id,
            pairs=top_pairs,
        )

        return top_pairs_snapshot
