import asyncio
from typing import Optional

from ipfs_client.main import AsyncIPFSClient
from redis import asyncio as aioredis
from pooler.modules.protocol_state.utils.bz2_transform import bz2_archive_transformation, bz2_unzip

from pooler.utils.callback_helpers import GenericProcessorMultiProjectAggregate
from pooler.utils.data_utils import get_project_epoch_snapshot, get_project_first_epoch
from pooler.utils.data_utils import get_tail_epoch_id
from pooler.utils.default_logger import logger
from pooler.utils.models.data_models import ProjectSpecificState
from pooler.utils.models.data_models import ProtocolState
from pooler.utils.models.message_models import PowerloomCalculateAggregateMessage
from pooler.utils.redis.redis_keys import project_finalized_data_zset
from pooler.utils.rpc import RpcHelper


class ProtocolStateProcessor(GenericProcessorMultiProjectAggregate):
    def __init__(self) -> None:
        # TODO: correctly configure transformation lambdas
        self.transformation_lambdas = [bz2_archive_transformation]
        self._logger = logger.bind(module='ProtocolStateProcessor')
        self.export_time_window_in_seconds = 86400

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
        self._logger.info(
            'Exporting protocol state for epoch released at ID {}, until epoch ID {}',
            msg_obj.epochId, msg_obj.epochId - 1
        )

        epoch_id = msg_obj.epochId
        self._protocol_state_query_semaphore = asyncio.BoundedSemaphore(10)
        protocol_state_project_first_epoch_id = await get_project_first_epoch(
            redis, protocol_state_contract, anchor_rpc_helper, project_id,
        )
        # build state from scratch
        if protocol_state_project_first_epoch_id == 0:
            self._logger.info('Protocol state project\'s first epoch is 0, building state from scratch')
            state = await self.export(epoch_id - 1, redis, anchor_rpc_helper, protocol_state_contract)
            return state
        else:
            self._logger.info('Protocol state project\'s first epoch is {}, building from previous state', protocol_state_project_first_epoch_id)
            previous_protocol_snapshot_data = await get_project_epoch_snapshot(
                redis, protocol_state_contract, anchor_rpc_helper, ipfs_reader, msg_obj.epochId - 1, project_id, bytes_mode=True,
            )
            if previous_protocol_snapshot_data:
                protocol_snapshot_data = bz2_unzip(previous_protocol_snapshot_data)
                state = ProtocolState.parse_raw(protocol_snapshot_data)
                last_head_marker = state.synced_till_epoch_id


        state = await self.export(epoch_id - 1, redis, anchor_rpc_helper, protocol_state_contract)

        return state

    async def prelim_load(self, redis: aioredis.Redis, anchor_rpc_helper: RpcHelper, protocol_state_contract):
        state_query_call_tasks = []
        all_project_ids_task = protocol_state_contract.functions.getProjects()
        state_query_call_tasks.append(all_project_ids_task)
        results = await anchor_rpc_helper.web3_call(state_query_call_tasks, redis)
        # print(results)
        # current epoch ID query returned as a list representing the ordered array of elements (begin, end, epochID)
        # of the struct and the other list has only element corresponding to the single level structure
        # of the struct EpochInfo in the contract
        all_project_ids: list = results[0]
        self._logger.debug('Getting first epoch ID against all projects')
        project_id_first_epoch_query_tasks = [
            # get project first epoch ID
            get_project_first_epoch(
                redis, protocol_state_contract, anchor_rpc_helper, project_id,
            ) for project_id in all_project_ids
            # self._protocol_state_contract.functions.projectFirstEpochId(project_id) for project_id in all_project_ids
        ]
        project_to_first_epoch_id_results = await asyncio.gather(
            *project_id_first_epoch_query_tasks, return_exceptions=True,
        )
        self._logger.debug(
            'Fetched {} results against first epoch IDs successfully', len(
                list(
                    filter(
                        lambda x: x is not None and not isinstance(x, Exception),
                        project_to_first_epoch_id_results,
                    ),
                ),
            ),
        )
        project_id_first_epoch_id_map = dict(zip(all_project_ids, project_to_first_epoch_id_results))
        return project_id_first_epoch_id_map, all_project_ids

    async def _export_project_state(
        self,
        project_id,
        first_epoch_id,
        end_epoch_id,
        redis: aioredis.Redis,
        anchor_rpc_helper: RpcHelper,
        protocol_state_contract,
        prev_project_state: Optional[ProjectSpecificState] = None,
    ) -> ProjectSpecificState:

        self._logger.debug('Exporting project state for {}', project_id)
        if not prev_project_state:
            project_state = ProjectSpecificState.construct()
            project_state.first_epoch_id = first_epoch_id
            project_state.finalized_cids = dict()
        else:
            project_state = prev_project_state
        self._logger.debug('Project {} first epoch ID: {}', project_id, first_epoch_id)
        # TODO: add necessary logs below to track calculations
        # TODO: review tail epoch ID helper parameters in case project's first epoch ID is pre-fetched
        state_export_tail_marker, extrapolated_flag = await get_tail_epoch_id(
            redis_conn=redis,
            state_contract_obj=protocol_state_contract,
            rpc_helper=anchor_rpc_helper,
            current_epoch_id=end_epoch_id,
            time_in_seconds=self.export_time_window_in_seconds,
            project_id=project_id,
        )
        if not prev_project_state:
            cids_r = await redis.zrangebyscore(
                name=project_finalized_data_zset(project_id),
                min=max(first_epoch_id, state_export_tail_marker),
                max=end_epoch_id,
                withscores=True,
            )
            # TODO: check for null CIDs in case of bad caching?
            if cids_r:
                [project_state.finalized_cids.update({int(eid): cid}) for cid, eid in cids_r]
        else:
            cids_to_append = await redis.zrangebyscore(
                name=project_finalized_data_zset(project_id),
                min=max(prev_project_state.finalized_cids.keys()) + 1,
                max=end_epoch_id,
                withscores=True,
            )
            [project_state.finalized_cids.update({int(eid): cid}) for cid, eid in cids_to_append]
            epoch_ids_moved_ahead_count = end_epoch_id - max(prev_project_state.finalized_cids.keys())
            oldest_epoch_id = min(prev_project_state.finalized_cids.keys())
            # means presently the entire span of epochs have crossed 24 hours, so remove older CIDs
            if not extrapolated_flag:
                [project_state.finalized_cids.pop(oldest_epoch_id + _) for _ in range(epoch_ids_moved_ahead_count)]
        return project_state

    async def export(
        self,
        state_export_head_marker,
        redis: aioredis.Redis,
        anchor_rpc_helper: RpcHelper,
        protocol_state_contract,
    ):
        project_id_first_epoch_id_map, all_project_ids = await self.prelim_load(
            redis, anchor_rpc_helper, protocol_state_contract,
        )
        state = ProtocolState.construct()
        state.epochId = state_export_head_marker
        state.synced_till_epoch_id = state_export_head_marker
        state.project_specific_states = dict()

        # Generate project specific state in batches
        batch_size = 10
        project_states = []
        for i in range(0, len(all_project_ids), batch_size):
            project_state_tasks = [
                self._export_project_state(
                    project_id,
                    project_id_first_epoch_id_map[project_id],
                    state_export_head_marker,
                    redis,
                    anchor_rpc_helper,
                    protocol_state_contract,
                )
                for project_id in all_project_ids[i:i + batch_size]

            ]
            project_state_results = await asyncio.gather(*project_state_tasks, return_exceptions=True)
            project_states.extend(project_state_results)

        for project_id, project_state in zip(all_project_ids, project_states):

            if isinstance(project_state, Exception):
                self._logger.error(
                    'Error exporting project state for project {}: {}',
                    project_id, project_state,
                )
                continue

            state.project_specific_states.update({project_id: project_state})

        self._logger.info('Exported state for {} projects', len(state.project_specific_states))

        return state
