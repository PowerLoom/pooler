import asyncio
import concurrent.futures
from collections import defaultdict
from typing import Dict

from ipfs_client.main import AsyncIPFSClient
from redis import asyncio as aioredis

from pooler.utils.callback_helpers import GenericProcessorMultiProjectAggregate
from pooler.utils.data_utils import get_project_first_epoch
from pooler.utils.data_utils import get_tail_epoch_id
from pooler.utils.data_utils import w3_get_and_cache_finalized_cid
from pooler.utils.default_logger import logger
from pooler.utils.models.data_models import ProjectSpecificState
from pooler.utils.models.data_models import ProtocolState
from pooler.utils.models.message_models import PowerloomCalculateAggregateMessage
from pooler.utils.redis.redis_keys import project_finalized_data_zset
from pooler.utils.rpc import RpcHelper
from pooler.utils.utility_functions import acquire_bounded_semaphore


class ProtocolStateProcessor(GenericProcessorMultiProjectAggregate):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
        self._logger = logger.bind(module='ProtocolStateProcessor')
        self.export_time_window_in_seconds = 3600

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
        self._logger.info(f'Exporting Project state for {msg_obj}')

        epoch_id = msg_obj.epochId
        self._protocol_state_query_semaphore = asyncio.BoundedSemaphore(10)

        state = await self.export(epoch_id - 1, redis, anchor_rpc_helper, protocol_state_contract)

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

    @acquire_bounded_semaphore
    async def _load_finalized_cids_from_contract(
        self,
        project_id,
        epoch_id_list,
        semaphore,
        redis: aioredis.Redis,
        anchor_rpc_helper: RpcHelper,
        protocol_state_contract,
    ) -> Dict[int, str]:
        """
        Fetches finalized CIDs for a project against a given list of epoch IDs from the contract
        and caches them in Redis
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
                        redis_conn=redis,
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
        self._logger.error(
            'Could not fetch finalized CIDs for project {} against epoch IDs: {}',
            project_id, list(filter(lambda x: x not in eid_cid_map, epoch_id_list)),
        )
        return eid_cid_map

    async def _export_project_state(
        self,
        project_id,
        first_epoch_id,
        end_epoch_id,
        redis: aioredis.Redis,
        anchor_rpc_helper: RpcHelper,
        protocol_state_contract,
    ) -> ProjectSpecificState:

        self._logger.debug('Exporting project state for {}', project_id)
        project_state = ProjectSpecificState.construct()
        project_state.first_epoch_id = first_epoch_id
        self._logger.debug('Project {} first epoch ID: {}', project_id, first_epoch_id)
        project_state.finalized_cids = dict()

        state_export_tail_marker = await get_tail_epoch_id(
            redis_conn=redis,
            state_contract_obj=protocol_state_contract,
            rpc_helper=anchor_rpc_helper,
            current_epoch_id=end_epoch_id,
            time_in_seconds=self.export_time_window_in_seconds,
            project_id=project_id,
        )

        cids_r = await redis.zrangebyscore(
            name=project_finalized_data_zset(project_id),
            min=first_epoch_id,
            max=end_epoch_id,
            withscores=True,
        )

        if cids_r:
            [project_state.finalized_cids.update({int(eid): cid}) for cid, eid in cids_r]

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
        state.synced_till_epoch_id = state_export_head_marker
        state.project_specific_states = dict()
        exceptions = defaultdict()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_project = {
                executor.submit(
                    self._export_project_state, project_id, project_id_first_epoch_id_map[
                        project_id
                    ], state_export_head_marker, redis, anchor_rpc_helper, protocol_state_contract,
                ): project_id for project_id in all_project_ids
            }
        for future in concurrent.futures.as_completed(future_to_project):
            project_id = future_to_project[future]
            try:
                project_specific_state = future.result()
            except Exception as exc:
                exceptions['project'].update({project_id: str(exc)})
            else:
                null_cid_epochs = list(
                    filter(
                        lambda x: 'null' in project_specific_state.finalized_cids[x],
                        project_specific_state.finalized_cids.keys(),
                    ),
                )
                # recheck on the contract if they are indeed null
                self._logger.debug(
                    'Verifying CIDs against epoch IDs of project {} by re-fetching state from'
                    ' contract since they were found to be null in local cache: {}', project_id, null_cid_epochs,
                )
                rechecked_eid_cid_map = await self._load_finalized_cids_from_contract(
                    project_id=project_id,
                    epoch_id_list=null_cid_epochs,
                    semaphore=self._protocol_state_query_semaphore,
                    redis=redis,
                    anchor_rpc_helper=anchor_rpc_helper,
                    protocol_state_contract=protocol_state_contract,
                )
                project_specific_state.finalized_cids.update(rechecked_eid_cid_map)
                self._logger.debug(
                    'Exported {} finalized CIDs for project {}',
                    len(project_specific_state.finalized_cids), project_id,
                )
                state.project_specific_states[project_id] = project_specific_state
        state_json = state.json()

        self._logger.error(state_json)

        return state_json
