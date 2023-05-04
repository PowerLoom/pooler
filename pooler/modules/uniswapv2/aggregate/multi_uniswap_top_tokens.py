from redis import asyncio as aioredis

from ..utils.helpers import get_pair_metadata
from ..utils.models.message_models import UniswapPairTotalReservesSnapshot
from ..utils.models.message_models import UniswapTopTokenSnapshot
from ..utils.models.message_models import UniswapTopTokensSnapshot
from ..utils.models.message_models import UniswapTradesAggregateSnapshot
from pooler.utils.aggregation_helper import get_project_epoch_snapshot
from pooler.utils.aggregation_helper import get_sumbmission_data_bulk
from pooler.utils.callback_helpers import GenericProcessorMultiProjectAggregate
from pooler.utils.default_logger import logger
from pooler.utils.ipfs.async_ipfshttpclient.main import AsyncIPFSClient
from pooler.utils.models.message_models import PowerloomCalculateAggregateMessage
from pooler.utils.rpc import RpcHelper


class AggreagateTopTokensProcessor(GenericProcessorMultiProjectAggregate):
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
        ipfs_reader: AsyncIPFSClient,
        protocol_state_contract,
        project_id: str,

    ):

        self._logger.info(f'Calculating top tokens data for {msg_obj}')
        epoch_id = msg_obj.epochId

        snapshot_mapping = {}
        projects_metadata = {}

        snapshot_data = await get_sumbmission_data_bulk(
            redis, [msg.snapshotCid for msg in msg_obj.messages], ipfs_reader,
        )

        for i in range(len(msg_obj.messages)):
            msg = msg_obj.messages[i]
            if not snapshot_data[i]:
                continue
            if 'reserves' in msg.projectId:
                snapshot = UniswapPairTotalReservesSnapshot.parse_raw(snapshot_data[i])
            elif 'volume' in msg.projectId:
                snapshot = UniswapTradesAggregateSnapshot.parse_raw(snapshot_data[i])
            snapshot_mapping[msg.projectId] = snapshot

            contract_address = project_id.split('_')[-2]
            pair_metadata = await get_pair_metadata(
                contract_address,
                redis_conn=redis,
                rpc_helper=rpc_helper,
            )

            projects_metadata[project_id] = pair_metadata

        all_tokens = set()

        # iterate over all snapshots and generate token data
        token_data = {}
        for project_id in snapshot_mapping.keys():
            snapshot = snapshot_mapping[project_id]
            project_metadata = projects_metadata[project_id]

            token0 = project_metadata['token0']
            token1 = project_metadata['token1']

            if token0['address'] not in token_data:
                token_data[token0['address']] = {
                    'address': token0['address'],
                    'name': token0['name'],
                    'symbol': token0['symbol'],
                    'decimals': token0['decimals'],
                    'price': 0,
                    'volume24h': 0,
                    'liquidity': 0,
                    'priceChange24h': 0,
                }

            if token1['address'] not in token_data:
                token_data[token1['address']] = {
                    'address': token1['address'],
                    'name': token1['name'],
                    'symbol': token1['symbol'],
                    'decimals': token1['decimals'],
                    'price': 0,
                    'volume24h': 0,
                    'liquidity': 0,
                    'priceChange24h': 0,
                }

            if 'reserves' in project_id:
                max_epoch_block = snapshot.chainHeightRange.end

                token_data[token0['address']]['price'] = snapshot.token0Price[max_epoch_block]
                token_data[token1['address']]['price'] = snapshot.token1Price[max_epoch_block]

                token_data[token0['address']]['liquidity'] += snapshot.token0ReservesUSD[max_epoch_block]
                token_data[token1['address']]['liquidity'] += snapshot.token1ReservesUSD[max_epoch_block]

            elif 'volume' in project_id:

                token_data[token0['address']]['volume24h'] += snapshot.token0TradeVolumeUSD
                token_data[token1['address']]['volume24h'] += snapshot.token1TradeVolumeUSD

        previous_top_tokens_snapshot_data = get_project_epoch_snapshot(
            redis, protocol_state_contract, anchor_rpc_helper, ipfs_reader, epoch_id - 1, project_id,
        )

        if previous_top_tokens_snapshot_data:
            previous_top_tokens_snapshot = UniswapTopTokensSnapshot.parse_raw(previous_top_tokens_snapshot_data)
            for token in previous_top_tokens_snapshot.tokens:
                if token.address in token_data:
                    price_before_24h = token.price

                    token_data[token.address]['priceChange24h'] = (
                        token_data[token.address]['price'] - price_before_24h
                    ) / price_before_24h * 100

        top_tokens = []
        for token in token_data.values():
            top_tokens.append(UniswapTopTokenSnapshot.parse_obj(**token))

        top_tokens = sorted(top_tokens, key=lambda x: x.liquidity, reverse=True)

        top_tokens_snapshot = UniswapTopTokensSnapshot(
            epochId=epoch_id,
            tokens=top_tokens,
        )

        return top_tokens_snapshot
