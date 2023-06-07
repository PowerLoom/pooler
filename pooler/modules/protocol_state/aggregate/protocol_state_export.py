import asyncio

from ipfs_client.main import AsyncIPFSClient
from redis import asyncio as aioredis

from pooler.utils.callback_helpers import GenericProcessorMultiProjectAggregate
from pooler.utils.data_utils import get_project_first_epoch
from pooler.utils.data_utils import get_tail_epoch_id
from pooler.utils.default_logger import logger
from pooler.utils.models.data_models import ProjectSpecificState
from pooler.utils.models.data_models import ProtocolState
from pooler.utils.models.message_models import PowerloomCalculateAggregateMessage
from pooler.utils.redis.redis_keys import project_finalized_data_zset
from pooler.utils.rpc import RpcHelper


class ProtocolStateProcessor(GenericProcessorMultiProjectAggregate):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
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

        state_export_tail_marker, _ = await get_tail_epoch_id(
            redis_conn=redis,
            state_contract_obj=protocol_state_contract,
            rpc_helper=anchor_rpc_helper,
            current_epoch_id=end_epoch_id,
            time_in_seconds=self.export_time_window_in_seconds,
            project_id=project_id,
        )

        cids_r = await redis.zrangebyscore(
            name=project_finalized_data_zset(project_id),
            min=max(first_epoch_id, state_export_tail_marker),
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
        state.epoch_id = state_export_head_marker
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

        state_json = state.json()

        self._logger.error(state_json)

        return state_json
