import asyncio
import bz2
import concurrent.futures
import io
import json
import resource
import sys
from collections import defaultdict
from typing import Dict

import pydantic
import redis
import uvloop
from redis import asyncio as aioredis
from web3 import Web3

from snapshotter.settings.config import settings
from snapshotter.utils.data_utils import get_project_first_epoch
from snapshotter.utils.data_utils import w3_get_and_cache_finalized_cid
from snapshotter.utils.default_logger import logger
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.models.data_models import ProjectSpecificState
from snapshotter.utils.models.data_models import ProtocolState
from snapshotter.utils.redis.redis_conn import REDIS_CONN_CONF
from snapshotter.utils.redis.redis_conn import RedisPoolCache
from snapshotter.utils.redis.redis_keys import project_finalized_data_zset
from snapshotter.utils.redis.redis_keys import project_first_epoch_hmap
from snapshotter.utils.rpc import RpcHelper
from snapshotter.utils.utility_functions import acquire_bounded_semaphore


class ProtocolStateLoader:
    _anchor_rpc_helper: RpcHelper
    _redis_conn: aioredis.Redis
    _protocol_state_query_semaphore: asyncio.BoundedSemaphore

    @acquire_bounded_semaphore
    async def _load_finalized_cids_from_contract_in_epoch_range(self, project_id, begin_epoch_id, cur_epoch_id, semaphore):
        """
        Fetches finalized CIDs for a project against an epoch ID range from the contract and caches them in Redis
        """
        epoch_id_fetch_batch_size = 20
        for e in range(begin_epoch_id, cur_epoch_id + 1, epoch_id_fetch_batch_size):
            self._logger.info(
                'Fetching finalized CIDs for project {} in epoch range {} to {}',
                project_id, e, min(e + epoch_id_fetch_batch_size, cur_epoch_id + 1) - 1,
            )
            r = await asyncio.gather(
                *[
                    w3_get_and_cache_finalized_cid(
                        project_id=project_id,
                        rpc_helper=self._anchor_rpc_helper,
                        epoch_id=epoch_id,
                        redis_conn=self._redis_conn,
                        state_contract_obj=self._protocol_state_contract,
                    )
                    for epoch_id in range(e, min(e + epoch_id_fetch_batch_size, cur_epoch_id + 1))
                ], return_exceptions=True,
            )
            for idx, e in enumerate(r):
                if isinstance(e, Exception):
                    self._logger.error(
                        'Error fetching finalized CIDs for project {} in epoch {}: {}',
                        project_id, begin_epoch_id + idx, e,
                    )
                else:
                    self._logger.trace(
                        'Fetched finalized CIDs for project {} in epoch {}: e',
                        project_id, begin_epoch_id + idx,
                    )

    @acquire_bounded_semaphore
    async def _load_finalized_cids_from_contract(self, project_id, epoch_id_list, semaphore) -> Dict[int, str]:
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
                        rpc_helper=self._anchor_rpc_helper,
                        epoch_id=epoch_id,
                        redis_conn=self._redis_conn,
                        state_contract_obj=self._protocol_state_contract,
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

    async def _init_redis_pool(self):
        """
        Initializes the Redis connection pool and populates it with connections.
        """
        self._aioredis_pool = RedisPoolCache(pool_size=1000)
        await self._aioredis_pool.populate()
        self._redis_conn = self._aioredis_pool._aioredis_pool

    async def _init_rpc_helper(self):
        """
        Initializes the RPC helper and sets the protocol state contract.

        This method creates an instance of RpcHelper using the specified RPC settings.
        It also reads the protocol ABI from the settings and sets the protocol state contract.

        Returns:
            None
        """
        self._anchor_rpc_helper = RpcHelper(rpc_settings=settings.anchor_chain_rpc)
        protocol_abi = read_json_file(settings.protocol_state.abi, self._logger)
        self._protocol_state_contract = self._anchor_rpc_helper.get_current_node()['web3_client'].eth.contract(
            address=Web3.toChecksumAddress(
                settings.protocol_state.address,
            ),
            abi=protocol_abi,
        )

    async def init(self):
        """
        Initializes the object by setting up the logger, initializing the Redis pool,
        initializing the RPC helper, and creating a bounded semaphore for protocol state queries.
        """
        self._logger = logger.bind(
            module=f'Powerloom|ProtocolStateLoader|{settings.namespace}-{settings.instance_id[:5]}',
        )
        await self._init_redis_pool()
        await self._init_rpc_helper()
        self._protocol_state_query_semaphore = asyncio.BoundedSemaphore(10)

    async def prelim_load(self):
        """
        Performs preliminary loading of protocol state data.

        Returns:
            Tuple: A tuple containing the current epoch ID, a dictionary mapping project IDs to their first epoch IDs,
                    and a list of all project IDs.
        """
        await self.init()
        state_query_call_tasks = []
        cur_epoch_id_task = self._protocol_state_contract.functions.currentEpoch(settings.data_market_id)
        state_query_call_tasks.append(cur_epoch_id_task)
        all_project_ids_task = self._protocol_state_contract.functions.getProjects(settings.data_market_id)
        state_query_call_tasks.append(all_project_ids_task)
        results = await self._anchor_rpc_helper.web3_call(state_query_call_tasks, self._redis_conn)
        # print(results)
        # current epoch ID query returned as a list representing the ordered array of elements (begin, end, epochID) of the struct
        # and the other list has only element corresponding to the single level structure of the struct EpochInfo in the contract
        cur_epoch_id = results[0][-1]
        all_project_ids: list = results[1]
        self._logger.debug('Getting first epoch ID against all projects')
        project_id_first_epoch_query_tasks = [
            # get project first epoch ID
            get_project_first_epoch(
                self._redis_conn, self._protocol_state_contract, self._anchor_rpc_helper, project_id,
            ) for project_id in all_project_ids
            # self._protocol_state_contract.functions.projectFirstEpochId(project_id) for project_id in all_project_ids
        ]
        project_to_first_epoch_id_results = await asyncio.gather(*project_id_first_epoch_query_tasks, return_exceptions=True)
        self._logger.debug(
            'Fetched {} results against first epoch IDs successfully', len(
                list(filter(lambda x: x is not None and not isinstance(x, Exception), project_to_first_epoch_id_results)),
            ),
        )
        project_id_first_epoch_id_map = dict(zip(all_project_ids, project_to_first_epoch_id_results))
        return cur_epoch_id, project_id_first_epoch_id_map, all_project_ids

    def _export_project_state(self, project_id, first_epoch_id, end_epoch_id, redis_conn: redis.Redis) -> ProjectSpecificState:
        """
        Export the project state for a specific project.

        Args:
            project_id (str): The ID of the project.
            first_epoch_id (int): The ID of the first epoch.
            end_epoch_id (int): The ID of the last epoch.
            redis_conn (redis.Redis): The Redis connection.

        Returns:
            ProjectSpecificState: The exported project state.
        """
        self._logger.debug('Exporting project state for {}', project_id)
        project_state = ProjectSpecificState.construct()
        project_state.first_epoch_id = first_epoch_id
        self._logger.debug('Project {} first epoch ID: {}', project_id, first_epoch_id)
        project_state.finalized_cids = dict()
        cids_r = redis_conn.zrangebyscore(
            name=project_finalized_data_zset(project_id),
            min=first_epoch_id,
            max=end_epoch_id,
            withscores=True,
        )
        if cids_r:
            [project_state.finalized_cids.update({int(eid): cid}) for cid, eid in cids_r]
        # null_cid_epochs = list(filter(lambda x: 'null' in project_state.finalized_cids[x], project_state.finalized_cids.keys()))
        # # recheck on the contract if they are indeed null
        # self._logger.debug('Verifying CIDs against epoch IDs of project {} by re-fetching state from contract since they were found to be null in local cache: {}', project_id, null_cid_epochs)
        # rechecked_eid_cid_map = asyncio.get_event_loop().run_until_complete(self._load_finalized_cids_from_contract(
        #     project_id, null_cid_epochs, self._protocol_state_query_semaphore,
        # ))
        # project_state.finalized_cids.update(rechecked_eid_cid_map)
        # self._logger.debug('Exported {} finalized CIDs for project {}', len(project_state.finalized_cids), project_id)
        return project_state

    def export(self):
        """
        Export the protocol state to a compressed JSON file.

        This method runs the preliminary load, retrieves the current epoch ID, project ID mapping,
        and all project IDs. It then exports the project-specific states and finalized CIDs for each project.
        The exported state is saved as a compressed JSON file named 'state.json.bz2'.

        Returns:
            None
        """
        asyncio.get_event_loop().run_until_complete(self.prelim_load())
        state = ProtocolState.construct()
        r = redis.Redis(**REDIS_CONN_CONF, max_connections=20, decode_responses=True)
        cur_epoch_id, project_id_first_epoch_id_map, all_project_ids = asyncio.get_event_loop().run_until_complete(self.prelim_load())
        state.synced_till_epoch_id = cur_epoch_id
        state.project_specific_states = dict()
        exceptions = defaultdict()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_project = {
                executor.submit(
                    self._export_project_state, project_id, project_id_first_epoch_id_map[project_id], cur_epoch_id, r,
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
                        lambda x: 'null' in project_specific_state.finalized_cids[x], project_specific_state.finalized_cids.keys(
                        ),
                    ),
                )
                # recheck on the contract if they are indeed null
                self._logger.debug(
                    'Verifying CIDs against epoch IDs of project {} by re-fetching state from contract since they were found to be null in local cache: {}', project_id, null_cid_epochs,
                )
                rechecked_eid_cid_map = asyncio.get_event_loop().run_until_complete(
                    self._load_finalized_cids_from_contract(
                        project_id=project_id, epoch_id_list=null_cid_epochs, semaphore=self._protocol_state_query_semaphore,
                    ),
                )
                project_specific_state.finalized_cids.update(rechecked_eid_cid_map)
                self._logger.debug(
                    'Exported {} finalized CIDs for project {}',
                    len(project_specific_state.finalized_cids), project_id,
                )
                state.project_specific_states[project_id] = project_specific_state
        state_json = state.json()
        with bz2.open('state.json.bz2', 'wb') as f:
            with io.TextIOWrapper(f, encoding='utf-8') as enc:
                enc.write(state_json)
        self._logger.info('Exported state.json.bz2')

    def _load_project_state(self, project_id, project_state: ProjectSpecificState, redis_conn: redis.Redis):
        """
        Loads the project state for a specific project.

        Args:
            project_id (str): The ID of the project.
            project_state (ProjectSpecificState): The project-specific state object.
            redis_conn (redis.Redis): The Redis connection object.

        Returns:
            None
        """
        self._logger.debug('Loading project state for {}', project_id)
        redis_conn.hset(project_first_epoch_hmap(), project_id, project_state.first_epoch_id)
        self._logger.debug('Loaded first epoch ID {} for project {}', project_state.first_epoch_id, project_id)
        try:
            s = redis_conn.zadd(
                name=project_finalized_data_zset(project_id),
                mapping={v: k for k, v in project_state.finalized_cids.items()},
            )
        except:
            self._logger.error('Error while loading finalized CIDs for project {}', project_id)
        else:
            self._logger.debug('Loaded {} finalized CIDs for project {}', s, project_id)

    def load(self, file_name='state.json.bz2'):
        """
        Loads the protocol state from a file.

        Args:
            file_name (str): The name of the file to load the state from. Default is 'state.json.bz2'.
        """
        asyncio.get_event_loop().run_until_complete(self.init())
        r = redis.Redis(**REDIS_CONN_CONF, max_connections=20, decode_responses=True)
        self._logger.debug('Loading state from file {}', file_name)
        with bz2.open(file_name, 'rb') as f:
            state_json = f.read()
        try:
            state = ProtocolState.parse_raw(state_json)
        except pydantic.ValidationError as e:
            self._logger.opt(exception=True).error('Error while parsing state file: {}', e)
            with open('state_parse_error.json', 'w') as f:
                json.dump(e.errors(), f)
            return
        self._logger.debug('Loading state from file {}', file_name)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_project = {
                executor.submit(
                    self._load_project_state, project_id, ProjectSpecificState.parse_obj(
                        project_state,
                    ), r,
                ): project_id for project_id, project_state in state.project_specific_states.items()
            }
        for future in concurrent.futures.as_completed(future_to_project):
            project_id = future_to_project[future]
            try:
                project_specific_state = future.result()
            except Exception as exc:
                self._logger.opt(exception=True).error('Error while loading project state for {}: {}', project_id, exc)
            else:
                self._logger.debug('Loaded project state for {}', project_id)
        self._logger.debug('Loaded state from file {}', file_name)


if __name__ == '__main__':
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(
        resource.RLIMIT_NOFILE,
        (settings.rlimit.file_descriptors, hard),
    )
    state_loader_exporter = ProtocolStateLoader()
    asyncio.get_event_loop().run_until_complete(state_loader_exporter.init())
    if sys.argv[1] == 'export':
        ProtocolStateLoader().export()
    elif sys.argv[1] == 'load':
        ProtocolStateLoader().load()
