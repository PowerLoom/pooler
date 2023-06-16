import asyncio
from typing import Dict, Optional

from ipfs_client.main import AsyncIPFSClient
from redis import asyncio as aioredis
from pooler.modules.protocol_state.utils.bz2_transform import bz2_archive_transformation, bz2_unzip

from pooler.utils.callback_helpers import GenericProcessorMultiProjectAggregate
from pooler.utils.data_utils import get_project_epoch_snapshot, get_project_first_epoch, w3_get_and_cache_finalized_cid
from pooler.utils.data_utils import get_tail_epoch_id
from pooler.utils.default_logger import logger
from pooler.utils.models.data_models import ProjectSpecificState, WrappedProtocolState
from pooler.utils.models.data_models import ProtocolState
from pooler.utils.models.message_models import PowerloomCalculateAggregateMessage
from pooler.utils.redis.redis_keys import project_finalized_data_zset
from pooler.utils.rpc import RpcHelper
from pooler.utils.utility_functions import acquire_bounded_semaphore


class ProtocolStateProcessor(GenericProcessorMultiProjectAggregate):
    def __init__(self) -> None:
        # TODO: correctly configure transformation lambdas
        self._transformation_lambdas = [bz2_archive_transformation]
        self._logger = logger.bind(module='ProtocolStateProcessor')
        self.export_time_window_in_seconds = 86400

    def transformation_lambdas(self):
        return self._transformation_lambdas

    @acquire_bounded_semaphore
    async def _load_finalized_cids_from_contract(
        self, 
        project_id, 
        epoch_id_list,
        anchor_rpc_helper,
        redis_conn,
        protocol_state_contract,
        semaphore: asyncio.BoundedSemaphore
    ) -> Dict[int, str]:
        """
        Fetches finalized CIDs for a project against a given list of epoch IDs from the contract and caches them in Redis
        """
        batch_size = 20
        self._logger.info(
            'Fetching finalized CIDs for project {} in epoch ID list: {}',
            project_id, epoch_id_list,
        )
        eid_cid_map = dict()
        for i in range(0, len(epoch_id_list), batch_size):
            r = await asyncio.gather(
                *[
                    w3_get_and_cache_finalized_cid(
                        project_id=project_id,
                        rpc_helper=anchor_rpc_helper,
                        epoch_id=epoch_id,
                        redis_conn=redis_conn,
                        state_contract_obj=protocol_state_contract,
                    )
                    for epoch_id in epoch_id_list[i:i + batch_size]
                ], return_exceptions=True,
            )
            for idx, e in enumerate(r):
                if isinstance(e, Exception):
                    self._logger.error(
                        'Error fetching finalized CID for project {} in epoch {}: {}',
                        project_id, epoch_id_list[i + idx], e,
                    )
                else:
                    self._logger.trace(
                        'Fetched finalized CID for project {} in epoch {}',
                        project_id, epoch_id_list[i + idx],
                    )
                    eid_cid_map[epoch_id_list[i + idx]] = e
        self._logger.error('Could not fetch finalized CIDs for project {} against epoch IDs: {}',
                           project_id, list(filter(lambda x: x not in eid_cid_map, epoch_id_list)))
        return eid_cid_map

    async def compute(
        self,
        msg_obj: PowerloomCalculateAggregateMessage,
        redis: aioredis.Redis,
        rpc_helper: RpcHelper,
        anchor_rpc_helper: RpcHelper,
        async_ipfs_client: AsyncIPFSClient,
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
            state_uncompressed_bytes = await self.export(epoch_id - 1, redis, anchor_rpc_helper, protocol_state_contract)
        else:
            self._logger.info('Protocol state project\'s first epoch is {}, building from previous state', protocol_state_project_first_epoch_id)
            previous_protocol_snapshot_data = await get_project_epoch_snapshot(
                redis, protocol_state_contract, anchor_rpc_helper, async_ipfs_client, msg_obj.epochId - 1, project_id
            )
            if previous_protocol_snapshot_data:
                previous_protocol_state_wrapped = WrappedProtocolState.parse_obj(previous_protocol_snapshot_data)
                self._logger.info('Previous protocol state at CID {}, attempting to fetch', previous_protocol_state_wrapped.protocol_state_cid)
                # TODO: fetch protocl state snapshot from local file system cache
                prev_state_compressed_bytes = await async_ipfs_client.cat(previous_protocol_state_wrapped.protocol_state_cid, bytes_mode=True)
                prev_protocol_state_bytes = bz2_unzip(prev_state_compressed_bytes)
                prev_protocol_state = ProtocolState.parse_raw(prev_protocol_state_bytes)
                prev_protocol_state.synced_till_epoch_id = epoch_id - 1
                all_project_ids = list(prev_protocol_state.project_specific_states.keys())
                batch_size = 10
                project_states = list()
                for i in range(0, len(all_project_ids), batch_size):
                    project_state_tasks = [
                        self._export_project_state(
                            project_id,
                            prev_protocol_state.project_specific_states[project_id].first_epoch_id,
                            epoch_id - 1,
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
                    prev_protocol_state.project_specific_states.update({project_id: project_state})
                state_uncompressed_bytes = prev_protocol_state.json().encode('utf-8')
            else:
                state_uncompressed_bytes = b''
        if state_uncompressed_bytes:
            # compress and upload to IPFS
            self._logger.debug('Protocol state project snapshot at epoch {}, compressing with bz2...', epoch_id)
            protocol_snapshot_data_compressed = bz2_archive_transformation(state_uncompressed_bytes, msg_obj)
            self._logger.debug('Protocol state project snapshot at epoch {}, uploading to IPFS...', epoch_id)
            # TODO: local file system caching of protocol state snapshots while uploading
            protocol_snapshot_cid = await async_ipfs_client.add_bytes(protocol_snapshot_data_compressed)
            self._logger.debug('Protocol state project snapshot at epoch {}, uploaded to IPFS with CID {}', epoch_id, protocol_snapshot_cid)
            return WrappedProtocolState(epochId=epoch_id, protocol_state_cid=protocol_snapshot_cid)

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

        self._logger.debug('Exporting project specific state for {}, at epoch ID {}', project_id, end_epoch_id)
        if not prev_project_state:
            project_state = ProjectSpecificState.construct()
            project_state.first_epoch_id = first_epoch_id
            project_state.finalized_cids = dict()
        else:
            project_state = prev_project_state
            self._logger.debug(
                'Found previous project specific state for {} synced till epoch ID {}',
                project_id, max(prev_project_state.finalized_cids.keys())
            )
        self._logger.debug('In project specific state export, project {} first epoch ID: {}', project_id, first_epoch_id)
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
            
            if cids_r:
                [project_state.finalized_cids.update({int(eid): cid}) for cid, eid in cids_r]
                null_cid_epochs = list(
                    filter(
                        lambda x: 'null' in project_state.finalized_cids[x],
                        project_state.finalized_cids.keys()))
                # recheck on the contract if they are indeed null
                self._logger.debug(
                    'Verifying CIDs against epoch IDs of project {} by re-fetching state from contract '
                    'since they were found to be null in local cache: {}',
                    project_id,
                    null_cid_epochs
                )
                rechecked_eid_cid_map = await self._load_finalized_cids_from_contract(
                    project_id=project_id,
                    epoch_id_list=null_cid_epochs,
                    anchor_rpc_helper=anchor_rpc_helper,
                    redis_conn=redis,
                    protocol_state_contract=protocol_state_contract,
                    semaphore=self._protocol_state_query_semaphore
                )
                project_state.finalized_cids.update(rechecked_eid_cid_map)
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
    ) -> bytes:
        project_id_first_epoch_id_map, all_project_ids = await self.prelim_load(
            redis, anchor_rpc_helper, protocol_state_contract,
        )
        state = ProtocolState.construct()
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

        return state.json().encode('utf-8')
