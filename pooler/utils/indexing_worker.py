import asyncio
import json
import math
from typing import Dict
from uuid import uuid4

import httpx._exceptions as httpx_exceptions
import web3.contract
from aio_pika import IncomingMessage
from pydantic import ValidationError
from redis import asyncio as aioredis
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential
from web3 import Web3

from pooler.settings.config import indexer_config
from pooler.settings.config import settings
from pooler.utils.generic_worker import GenericAsyncWorker
from pooler.utils.ipfs.async_ipfshttpclient.main import AsyncIPFSClient
from pooler.utils.ipfs.async_ipfshttpclient.main import AsyncIPFSClientSingleton
from pooler.utils.ipfs.retrieval_utils import retrieve_block_data
from pooler.utils.models.data_models import BlockRetrievalFlags
from pooler.utils.models.data_models import CachedDAGTailMarker
from pooler.utils.models.data_models import CachedIndexMarker
from pooler.utils.models.data_models import IndexSeek
from pooler.utils.models.data_models import RetrievedDAGBlock
from pooler.utils.models.data_models import TailAdjustmentCursor
from pooler.utils.models.message_models import PowerloomIndexingProcessMessage
from pooler.utils.redis import redis_keys
from pooler.utils.redis.rate_limiter import load_rate_limiter_scripts
from pooler.utils.rpc import RpcHelper


class IndexingAsyncWorker(GenericAsyncWorker):

    _source_chain_rpc_helper: RpcHelper
    _ipfs_singleton: AsyncIPFSClientSingleton
    _ipfs_writer_client: AsyncIPFSClient
    _ipfs_reader_client: AsyncIPFSClient
    _anchor_chain_rpc_helper: RpcHelper
    _dummy_w3_obj: Web3  # to help with constructing function call/transaction objects
    _anchor_chain_submission_contract_obj: web3.contract.Contract

    def __init__(self, name, **kwargs):
        super(IndexingAsyncWorker, self).__init__(name=name, **kwargs)

        self._task_types = []
        self._index_calculation_mapping = {}

        for indexing_project in indexer_config:
            type_ = indexing_project.project_type
            self._task_types.append(type_)
            self._index_calculation_mapping[type_] = (
                indexing_project.duration_in_seconds
            )
        self._asyncio_lock_map: Dict[str, asyncio.Lock] = dict()

    @retry(
        reraise=True, wait=wait_random_exponential(multiplier=1, max=20),
        # Randomly wait up to 2^x * 1 seconds between each retry until the range reaches 60 seconds
        # then randomly up to 20 seconds afterwards
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(httpx_exceptions.TransportError) | retry_if_exception_type(json.JSONDecodeError),
    )
    async def _httpx_wrap_call(self, url, json_body):
        resp = await self._httpx_client.post(
            url=url,
            json=json_body,
        )
        return resp.json()

    # TODO: Add interfaces and notifiers for indexing failure
    # @notify_on_task_failure
    async def _processor_task(self, msg_obj: PowerloomIndexingProcessMessage, task_type: str):
        """Function used to process the received message object."""
        self._logger.debug(
            'Processing callback: {}', msg_obj,
        )

        await self.init()

        if task_type not in self._index_calculation_mapping:
            self._logger.error(
                (
                    'No index calculation mapping found for task type'
                    f' {task_type}. Skipping...'
                ),
            )
            return

        self_unique_id = str(uuid4())
        cur_task: asyncio.Task = asyncio.current_task(
            asyncio.get_running_loop(),
        )
        cur_task.set_name(
            f'aio_pika.consumer|Processor|{task_type}|{msg_obj.contract}',
        )
        self._running_callback_tasks[self_unique_id] = cur_task

        if not self._rate_limiting_lua_scripts:
            self._rate_limiting_lua_scripts = await load_rate_limiter_scripts(
                self._redis_conn,
            )
        self._logger.debug(
            'Got epoch to process for {}: {}',
            task_type, msg_obj,
        )

        # TODO: test and update this
        await self._index_building_dag_finalization_callback(msg_obj, task_type)

        del self._running_callback_tasks[self_unique_id]

    async def _get_dag_cid_at_height(self, dag_block_height: int):
        tasks = [self._anchor_chain_submission_contract_obj.functions.finalizedDagCids(dag_block_height)]
        results = await self._source_chain_rpc_helper.web3_call(
            tasks=tasks,
            redis_conn=self._writer_redis_pool,
        )
        return results[0]

    # TODO: Handle missing/null payloads in DAG block by skipping over indexing
    async def _seek_tail(
            self,
            project_id: str,
            head_dag_cid: str,
            time_range: int,
    ):
        redis_conn: aioredis.Redis = self._writer_redis_pool
        head_block: RetrievedDAGBlock = await retrieve_block_data(
            project_id,
            head_dag_cid,
            self._ipfs_reader_client,
            BlockRetrievalFlags.dag_block_and_payload_data,
        )
        latest_block_in_head_epoch_timestamp = await self._source_chain_rpc_helper.batch_eth_get_block(
            from_block=head_block.data.payload['chainHeightRange']['end'],
            to_block=head_block.data.payload['chainHeightRange']['end'],
            redis_conn=self._writer_redis_pool,
        )
        head_timestamp = int(latest_block_in_head_epoch_timestamp[0]['result']['timestamp'], 16)
        tail_block_index = IndexSeek(dagBlockHead=head_block)
        if not settings.indexing_fast_track.enabled:
            cur_block = head_block
            cur_block_cid = head_dag_cid
            while True:
                prev_dag_cid = cur_block.prevCid['/'] if cur_block.prevCid else None
                if not prev_dag_cid:
                    if 'prevRoot' in cur_block and cur_block.prevRoot is not None:
                        prev_dag_cid = cur_block.prevRoot
                if prev_dag_cid:
                    self._logger.trace(
                        'Attempting to fetch prev DAG block at CID: {} | Current DAG block CID: {} height: {} ',
                        prev_dag_cid, cur_block_cid, cur_block.height,
                    )
                    prev_dag_block: RetrievedDAGBlock = await retrieve_block_data(
                        project_id,
                        cur_block.prevCid['/'],
                        self._ipfs_reader_client,
                        BlockRetrievalFlags.dag_block_and_payload_data,
                    )
                    self._logger.trace(
                        'Fetched prev DAG block at CID: {} height: {} | Current DAG block CID: {} height: {} | '
                        '{} | Difference from head timestamp: {}',
                        prev_dag_cid, prev_dag_block.height, cur_block_cid, cur_block.height, prev_dag_block,
                        head_timestamp - prev_dag_block.data.payload['timestamp'],
                    )
                    # check if source chain blocks included in epoch, use their timestamps
                    if prev_dag_block.data.payload:
                        epoch_blocks_range = prev_dag_block.data.payload['chainHeightRange']
                        self._logger.trace(
                            'Fetching source chain block details in block height range {}', epoch_blocks_range,
                        )
                        block_dets = await self._source_chain_rpc_helper.batch_eth_get_block(
                            from_block=epoch_blocks_range['begin'],
                            to_block=epoch_blocks_range['end'],
                            redis_conn=redis_conn,
                        )
                        block_timestamp_map = {
                            int(block['result']['number'], 16): int(block['result']['timestamp'], 16)
                            for block in block_dets
                        }
                        self._logger.trace(
                            'Fetched source chain block details in block height range {}', block_timestamp_map,
                        )
                        # scan from latest block in epoch to earliest to encounter first block that is within time range
                        for k in range(epoch_blocks_range['end'], epoch_blocks_range['begin'] - 1, -1):
                            if head_timestamp - block_timestamp_map[k] >= time_range:
                                tail_block_index.dagBlockTail = prev_dag_block
                                tail_block_index.dagBlockTailCid = prev_dag_cid
                                tail_block_index.sourceChainBlockNum = k
                                return tail_block_index
                    cur_block = prev_dag_block
                    cur_block_cid = prev_dag_cid
                else:
                    # end of known chain reached
                    break
        else:
            expected_source_blocks_to_tail = (head_timestamp - time_range) / \
                settings.indexing_fast_track.source_chain_block_time
            head_dag_height = head_block.height
            dag_blocks_to_tail = math.ceil(expected_source_blocks_to_tail / settings.indexing_fast_track.epoch_size)
            # TODO: consult decentralized state to find DAG CID at height (head_dag_height - dag_blocks_to_tail)
        return tail_block_index

    async def _adjust_tail(
            self,
            project_id: str,
            head_dag_cid: str,
            head_dag_height: int,
            time_range: int,
            last_recorded_tail_source_chain_marker: CachedIndexMarker,
    ):
        redis_conn: aioredis.Redis = self._writer_redis_pool
        cur_head_block: RetrievedDAGBlock = await retrieve_block_data(
            project_id,
            head_dag_cid,
            self._ipfs_reader_client,
            BlockRetrievalFlags.dag_block_and_payload_data,
        )
        latest_block_in_head_epoch_timestamp = await self._source_chain_rpc_helper.batch_eth_get_block(
            from_block=cur_head_block.data.payload['chainHeightRange']['end'],
            to_block=cur_head_block.data.payload['chainHeightRange']['end'],
            redis_conn=redis_conn,
        )
        last_recorded_index_tail_dag_block: RetrievedDAGBlock = await retrieve_block_data(
            project_id,
            last_recorded_tail_source_chain_marker.dagTail.cid,
            self._ipfs_reader_client,
            BlockRetrievalFlags.dag_block_and_payload_data,
        )
        iteration_cursor = TailAdjustmentCursor.construct()
        if (
            last_recorded_tail_source_chain_marker.dagTail.sourceChainBlockNum ==
            last_recorded_index_tail_dag_block.data.payload['chainHeightRange']['end']
        ):
            iteration_cursor.dag_block_height = last_recorded_tail_source_chain_marker.dagTail.height + 1
            iteration_cursor.dag_block_cid = await self._get_dag_cid_at_height(iteration_cursor.dag_block_height)
            iteration_cursor.dag_block = await retrieve_block_data(
                project_id,
                iteration_cursor.dag_block_cid,
                self._ipfs_reader_client,
                BlockRetrievalFlags.dag_block_and_payload_data,
            )
            iteration_cursor.epoch_range = iteration_cursor.dag_block.data.payload['chainHeightRange'][
                'begin'
            ], iteration_cursor.dag_block.data.payload['chainHeightRange']['end']
        else:
            iteration_cursor.dag_block_height = last_recorded_tail_source_chain_marker.dagTail.height
            iteration_cursor.dag_block = last_recorded_index_tail_dag_block
            iteration_cursor.dag_block_cid = last_recorded_tail_source_chain_marker.dagTail.cid
            iteration_cursor.epoch_range = last_recorded_tail_source_chain_marker.dagTail.sourceChainBlockNum + \
                1, iteration_cursor.dag_block.data.payload['chainHeightRange']['end']
        cur_head_timestamp = int(latest_block_in_head_epoch_timestamp[0]['result']['timestamp'], 16)
        tail_block_index = IndexSeek(dagBlockHead=cur_head_block)
        while True:
            block_dets = await self._source_chain_rpc_helper.batch_eth_get_block(
                from_block=iteration_cursor.epoch_range[0],
                to_block=iteration_cursor.epoch_range[1],
                redis_conn=redis_conn,
            )
            block_timestamp_map = {
                int(block['result']['number'], 16): int(block['result']['timestamp'], 16)
                for block in block_dets
            }
            self._logger.trace('Fetched source chain block details in block height range {}', block_timestamp_map)
            for k in range(iteration_cursor.epoch_range[1], iteration_cursor.epoch_range[0] - 1, -1):
                if cur_head_timestamp - block_timestamp_map[k] >= time_range:
                    tail_block_index.dagBlockTail = iteration_cursor.dag_block
                    tail_block_index.dagBlockTailCid = iteration_cursor.dag_block_cid
                    tail_block_index.sourceChainBlockNum = k
                    self._logger.debug(
                        'Adjusted tail index against new head height {}\'s epoch end {} | '
                        'Previous tail at height {} epoch block number {} against head CID {}\'s epoch end | '
                        'New tail at height {} epoch block number {}',
                        head_dag_height, cur_head_block.data.payload['chainHeightRange']['end'],
                        last_recorded_tail_source_chain_marker.dagTail.height,
                        last_recorded_tail_source_chain_marker.dagTail.sourceChainBlockNum,
                        last_recorded_tail_source_chain_marker.dagHeadCid,
                        tail_block_index.dagBlockTail.height, tail_block_index.sourceChainBlockNum,
                    )
                    return tail_block_index
            iteration_cursor.dag_block_height += 1
            if iteration_cursor.dag_block_height == head_dag_height:
                break
            iteration_cursor.dag_block_cid = await self._get_dag_cid_at_height(iteration_cursor.dag_block_height)
            iteration_cursor.dag_block = await retrieve_block_data(
                project_id,
                iteration_cursor.dag_block_cid,
                self._ipfs_reader_client,
                BlockRetrievalFlags.dag_block_and_payload_data,
            )
            iteration_cursor.epoch_range = iteration_cursor.dag_block.data.payload['chainHeightRange']['begin'], \
                iteration_cursor.dag_block.data.payload['chainHeightRange']['end']
        return tail_block_index

    async def _index_building_dag_finalization_callback(
        self,
        dag_finalization_cb: PowerloomIndexingProcessMessage,
        task_type: str,
    ):
        callback_dag_height = dag_finalization_cb.DAGBlockHeight
        # consult protocol state stored on smart contract for finalized DAG CID at this height
        head_dag_cid = await self._get_dag_cid_at_height(callback_dag_height)
        project_id = dag_finalization_cb.projectId
        redis_conn: aioredis.Redis = self._writer_redis_pool
        last_recorded_dag_height_index = await redis_conn.zrange(
            name=redis_keys.get_last_indexed_markers_zset(project_id),
            start=0,
            end=0,
            withscores=True,
            score_cast_func=int,
        )
        epoch_size = await redis_conn.get(redis_keys.get_project_epoch_size(project_id))
        if not epoch_size:
            self._logger.warning('Project ID %s recorded epoch size not found in cache', project_id)
            return
        # for eg:
        # last recorded finalization is at tentative height: 2.
        # zset: 2 -> {'dagTail': {height:, cid: , sourceChainBlockNum}}
        # present finalization is at tentative height: 3
        if not last_recorded_dag_height_index:
            tail_index: IndexSeek = await self._seek_tail(
                project_id, head_dag_cid, self._index_calculation_mapping[task_type],
            )
            self._logger.logger.debug(
                'Project ID {} | Sought tail index for time period {} seconds against head CID {} : {} ',
                project_id, self._index_calculation_mapping[task_type], head_dag_cid, tail_index,
            )
            index_record_to_cache = CachedIndexMarker(
                dagTail=CachedDAGTailMarker(
                    height=tail_index.dagBlockTail.height,
                    cid=tail_index.dagBlockTailCid,
                    sourceChainBlockNum=tail_index.sourceChainBlockNum,
                ),
                dagHeadCid=head_dag_cid,
            )
            await redis_conn.zadd(
                name=redis_keys.get_last_indexed_markers_zset(project_id),
                mapping={index_record_to_cache.json(): dag_finalization_cb.DAGBlockHeight},
            )
            # commit to index submission contract
            # TODO: send to transaction manager
        else:
            last_recorded_against_dag_head_height = int(last_recorded_dag_height_index[0][1])
            height_diff = callback_dag_height - last_recorded_against_dag_head_height - 1
            last_recorded_tail_source_chain_marker = CachedIndexMarker.parse_raw(last_recorded_dag_height_index[0][0])

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        task_type = message.routing_key.split('.')[-1]
        print(task_type)
        if task_type not in self._task_types:
            return

        self._logger.debug('task type: {}', task_type)

        try:
            msg_obj = PowerloomIndexingProcessMessage.parse_raw(message.body)
        except ValidationError as e:
            self._logger.opt(exception=True).error(
                (
                    'Bad message structure of callback processor. Error: {}'
                ),
                e,
            )
            return
        except Exception as e:
            self._logger.opt(exception=True).error(
                (
                    'Unexpected message structure of callback in processor. Error: {}'
                ),
                e,
            )
            return

        asyncio.ensure_future(self._processor_task(msg_obj=msg_obj, task_type=task_type))
        await message.ack()

    async def _init_indexing_worker(self):
        if not self._writer_redis_pool:
            self._writer_redis_pool = self._aioredis_pool.writer_redis_pool
            self._reader_redis_pool = self._aioredis_pool.reader_redis_pool

        if not self._ipfs_singleton:
            self._ipfs_singleton = AsyncIPFSClientSingleton()
            await self._ipfs_singleton.init_sessions()
            self._ipfs_writer_client = self._ipfs_singleton._ipfs_write_client
            self._ipfs_reader_client = self._ipfs_singleton._ipfs_read_client

        if not self._source_chain_rpc_helper:
            self._source_chain_rpc_helper = RpcHelper(rpc_settings=settings.source_chain_rpc)
            await self._source_chain_rpc_helper.init(self._writer_redis_pool)

        if not self._anchor_chain_rpc_helper:
            self._anchor_chain_rpc_helper = RpcHelper(rpc_settings=settings.anchor_chain_rpc)
            await self._anchor_chain_rpc_helper.init(self._writer_redis_pool)

        if not self._dummy_w3_obj:
            self._dummy_w3_obj = Web3()

        with open(settings.protocol_state.abi) as f:
            self._anchor_chain_submission_contract_obj = self._dummy_w3_obj.eth.contract(
                address=settings.protocol_state.address,
                abi=json.load(f),
            )

    async def init(self):
        await self._init_redis_pool()
        await self._init_httpx_client()
        await self._init_rpc_helper()
        await self._init_indexing_worker()


wkr = IndexingAsyncWorker('test')
wkr.start()
