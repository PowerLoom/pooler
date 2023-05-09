
import asyncio
import json
import resource
import uvloop
from redis import asyncio as aioredis
from web3 import Web3
from pooler.settings.config import settings
from pooler.utils.redis.redis_conn import RedisPoolCache
from pooler.utils.data_utils import get_project_first_epoch, w3_get_and_cache_finalized_cid
from pooler.utils.file_utils import read_json_file
from pooler.utils.ipfs.async_ipfshttpclient.main import AsyncIPFSClientSingleton
from pooler.utils.rpc import RpcHelper
from pooler.utils.default_logger import logger
from pooler.utils.utility_functions import acquire_bounded_semaphore


class ProtocolStateLoader:
    _anchor_rpc_helper: RpcHelper
    _redis_conn: aioredis.Redis
    _protocol_state_query_semaphore: asyncio.BoundedSemaphore

    @acquire_bounded_semaphore
    async def _load_finalized_cids(self, project_id, first_epoch_id, cur_epoch_id, semaphore):
        epoch_id_fetch_batch_size = 20
        for e in range(first_epoch_id, cur_epoch_id + 1, epoch_id_fetch_batch_size):
            self._logger.info('Fetching finalized CIDs for project {} in epoch range {} to {}', project_id, e, min(e + epoch_id_fetch_batch_size, cur_epoch_id + 1) - 1)
            r = await asyncio.gather(*[
                w3_get_and_cache_finalized_cid(
                    project_id=project_id,
                    rpc_helper=self._anchor_rpc_helper,
                    epoch_id=epoch_id,
                    redis_conn=self._redis_conn,
                    state_contract_obj=self._protocol_state_contract
                )
                for epoch_id in range(e, min(e + epoch_id_fetch_batch_size, cur_epoch_id + 1))
            ], return_exceptions=True)
            for idx, e in enumerate(r):
                if isinstance(e, Exception):
                    self._logger.error('Error fetching finalized CIDs for project {} in epoch {}: {}', project_id, first_epoch_id+idx, e)
                else:
                    self._logger.info('Fetched finalized CIDs for project {} in epoch {}', project_id, first_epoch_id+idx)
    
    async def _init_redis_pool(self):
        self._aioredis_pool = RedisPoolCache(pool_size=500)
        await self._aioredis_pool.populate()
        self._redis_conn = self._aioredis_pool._aioredis_pool

    async def _init_ipfs_client(self):
        self._ipfs_singleton = AsyncIPFSClientSingleton()
        await self._ipfs_singleton.init_sessions()
        self._ipfs_writer_client = self._ipfs_singleton._ipfs_write_client
        self._ipfs_reader_client = self._ipfs_singleton._ipfs_read_client

    async def _init_rpc_helper(self):
        self._anchor_rpc_helper = RpcHelper(rpc_settings=settings.anchor_chain_rpc)
        protocol_abi = read_json_file(settings.protocol_state.abi, self._logger)
        self._protocol_state_contract = self._anchor_rpc_helper.get_current_node()['web3_client'].eth.contract(
            address=Web3.toChecksumAddress(
                settings.protocol_state.address,
            ),
            abi=protocol_abi
        )

    async def init(self):
        self._logger = logger.bind(
            module=f'PowerLoom|ProtocolStateLoader|{settings.namespace}-{settings.instance_id[:5]}',
        )
        await self._init_redis_pool()
        await self._init_ipfs_client()
        await self._init_rpc_helper()
        self._protocol_state_query_semaphore = asyncio.BoundedSemaphore(10)

    async def main(self):
        await self.init()
        state_query_call_tasks = []
        cur_epoch_id_task = self._protocol_state_contract.functions.currentEpoch()
        state_query_call_tasks.append(cur_epoch_id_task)
        all_project_ids_task = self._protocol_state_contract.functions.getProjects()
        state_query_call_tasks.append(all_project_ids_task)
        results = await self._anchor_rpc_helper.web3_call(state_query_call_tasks, self._redis_conn)
        # print(results)
        # current epoch ID query returned as a list representing the ordered array of elements (begin, end, epochID) of the struct 
        # and the other list has only element corresponding to the single level structure of the struct EpochInfo in the contract
        cur_epoch_id = results[0][-1]
        all_project_ids: list = results[1]
        finalized_cids_map = dict()
        self._logger.debug('Getting first epoch ID against all projects')
        project_id_first_epoch_query_tasks = [
            # get project first epoch ID
            get_project_first_epoch(
                self._redis_conn, self._protocol_state_contract, self._anchor_rpc_helper, project_id
            ) for project_id in all_project_ids
            # self._protocol_state_contract.functions.projectFirstEpochId(project_id) for project_id in all_project_ids
        ]
        project_to_first_epoch_id_results = await asyncio.gather(*project_id_first_epoch_query_tasks, return_exceptions=True)
        self._logger.debug('Fetched {} results against first epoch IDs successfully', len(list(filter(lambda x: x is not None and not isinstance(x, Exception), project_to_first_epoch_id_results))))
        project_id_first_epoch_id_map = dict(zip(all_project_ids, project_to_first_epoch_id_results))
        # for each project load set of finalized CIDs from first epoch ID to currently marked epochID
        finalized_cid_load = await asyncio.gather(*[
            self._load_finalized_cids(project_id, project_id_first_epoch_id_map[project_id], cur_epoch_id, self._protocol_state_query_semaphore) for project_id in all_project_ids
        ], return_exceptions=False)
        # for idx, e in enumerate(finalized_cid_load):
        #     if isinstance(e, Exception):
        #         self._logger.error('Error fetching finalized CIDs for project {} in epoch {}: {}', all_project_ids[idx], project_id_first_epoch_id_map[all_project_ids[idx]], e)
        #     else:
        #         self._logger.info('Fetched finalized CIDs for project {} in epoch {}', all_project_ids[idx], project_id_first_epoch_id_map[all_project_ids[idx]])


if __name__ == '__main__':
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(
        resource.RLIMIT_NOFILE,
        (settings.rlimit.file_descriptors, hard),
    )
    asyncio.get_event_loop().run_until_complete(ProtocolStateLoader().main())

