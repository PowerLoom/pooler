import asyncio
import copy
import importlib
import json
import multiprocessing
import queue
import time
from collections import defaultdict
from functools import partial
from typing import Awaitable
from typing import Dict
from typing import List
from typing import Set
from uuid import uuid4

import uvloop
from aio_pika import IncomingMessage
from aio_pika import Message
from aio_pika.pool import Pool
from eth_utils.address import to_checksum_address
from eth_utils.crypto import keccak
from httpx import AsyncClient
from httpx import AsyncHTTPTransport
from httpx import Limits
from httpx import Timeout
from pydantic import ValidationError
from redis import asyncio as aioredis
from web3 import Web3

from snapshotter.settings.config import aggregator_config
from snapshotter.settings.config import preloaders
from snapshotter.settings.config import projects_config
from snapshotter.settings.config import settings
from snapshotter.utils.callback_helpers import get_rabbitmq_channel
from snapshotter.utils.callback_helpers import get_rabbitmq_robust_connection_async
from snapshotter.utils.data_utils import get_projects_list
from snapshotter.utils.data_utils import get_snapshot_submision_window
from snapshotter.utils.data_utils import get_source_chain_epoch_size
from snapshotter.utils.data_utils import get_source_chain_id
from snapshotter.utils.default_logger import logger
from snapshotter.utils.models.data_models import PreloaderAsyncFutureDetails
from snapshotter.utils.models.data_models import SnapshotterStates
from snapshotter.utils.models.data_models import SnapshotterStateUpdate
from snapshotter.utils.models.data_models import SnapshottersUpdatedEvent
from snapshotter.utils.models.message_models import EpochBase
from snapshotter.utils.models.message_models import PayloadCommitFinalizedMessage
from snapshotter.utils.models.message_models import PowerloomCalculateAggregateMessage
from snapshotter.utils.models.message_models import PowerloomProjectsUpdatedMessage
from snapshotter.utils.models.message_models import PowerloomSnapshotFinalizedMessage
from snapshotter.utils.models.message_models import PowerloomSnapshotProcessMessage
from snapshotter.utils.models.message_models import PowerloomSnapshotSubmittedMessage
from snapshotter.utils.models.settings_model import AggregateOn
from snapshotter.utils.redis.redis_conn import RedisPoolCache
from snapshotter.utils.redis.redis_keys import active_status_key
from snapshotter.utils.redis.redis_keys import epoch_id_epoch_released_key
from snapshotter.utils.redis.redis_keys import epoch_id_project_to_state_mapping
from snapshotter.utils.redis.redis_keys import project_finalized_data_zset
from snapshotter.utils.redis.redis_keys import snapshot_submission_window_key
from snapshotter.utils.rpc import RpcHelper


class ProcessorDistributor(multiprocessing.Process):
    _aioredis_pool: RedisPoolCache
    _redis_conn: aioredis.Redis

    def __init__(self, name, **kwargs):
        super(ProcessorDistributor, self).__init__(name=name, **kwargs)
        self._unique_id = f'{name}-' + keccak(text=str(uuid4())).hex()[:8]
        self._q = queue.Queue()
        self._rabbitmq_interactor = None
        self._shutdown_initiated = False
        self._rpc_helper = None
        self._source_chain_id = None
        self._projects_list = None
        self._consume_exchange_name = f'{settings.rabbitmq.setup.event_detector.exchange}:{settings.namespace}'
        self._consume_queue_name = (
            f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}'
        )
        self._initialized = False
        self._consume_queue_routing_key = f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}.*'
        self._callback_exchange_name = (
            f'{settings.rabbitmq.setup.callbacks.exchange}:{settings.namespace}'
        )
        self._payload_commit_exchange_name = (
            f'{settings.rabbitmq.setup.commit_payload.exchange}:{settings.namespace}'
        )
        self._payload_commit_routing_key = f'powerloom-backend-commit-payload:{settings.namespace}:{settings.instance_id}.Finalized'

        self.projects_config = copy.copy(projects_config)
        self._upcoming_project_changes = defaultdict(list)
        self._preload_completion_conditions: Dict[
            int, Awaitable,
        ] = defaultdict(dict)  # epoch ID to preloading complete event
        self._newly_added_projects = set()
        self._shutdown_initiated = False
        self._all_preload_tasks = set()
        self._project_type_config_mapping = dict()
        for project_config in self.projects_config:
            self._project_type_config_mapping[project_config.project_type] = project_config
            for proload_task in project_config.preload_tasks:
                self._all_preload_tasks.add(proload_task)

        self._preloader_compute_mapping = dict()
        self._async_transport = AsyncHTTPTransport(
            limits=Limits(
                max_connections=100,
                max_keepalive_connections=50,
                keepalive_expiry=None,
            ),
        )
        self._client = AsyncClient(
            base_url=settings.reporting.service_url,
            timeout=Timeout(timeout=5.0),
            follow_redirects=False,
            transport=self._async_transport,
        )

    async def _init_redis_pool(self):
        self._aioredis_pool = RedisPoolCache()
        await self._aioredis_pool.populate()
        self._redis_conn = self._aioredis_pool._aioredis_pool

    async def _init_rpc_helper(self):
        if not self._rpc_helper:
            self._rpc_helper = RpcHelper()
            self._anchor_rpc_helper = RpcHelper(rpc_settings=settings.anchor_chain_rpc)

    async def _init_rabbitmq_connection(self):
        self._rmq_connection_pool = Pool(
            get_rabbitmq_robust_connection_async,
            max_size=20, loop=asyncio.get_event_loop(),
        )
        self._rmq_channel_pool = Pool(
            partial(get_rabbitmq_channel, self._rmq_connection_pool), max_size=100,
            loop=asyncio.get_event_loop(),
        )

    async def _init_preloader_compute_mapping(self):
        if self._preloader_compute_mapping:
            return

        for preloader in preloaders:
            if preloader.task_type in self._all_preload_tasks:
                preloader_module = importlib.import_module(preloader.module)
                preloader_class = getattr(preloader_module, preloader.class_name)
                self._preloader_compute_mapping[preloader.task_type] = preloader_class

    async def init_worker(self):
        if not self._initialized:
            await self._init_redis_pool()
            await self._init_rpc_helper()
            await self._load_projects_metadata()
            await self._init_rabbitmq_connection()
            await self._init_preloader_compute_mapping()
            self._initialized = True

    async def _load_projects_metadata(self):
        if not self._projects_list:
            with open(settings.protocol_state.abi, 'r') as f:
                abi_dict = json.load(f)
            protocol_state_contract = self._anchor_rpc_helper.get_current_node()['web3_client'].eth.contract(
                address=Web3.toChecksumAddress(
                    settings.protocol_state.address,
                ),
                abi=abi_dict,
            )
            await get_source_chain_epoch_size(
                redis_conn=self._redis_conn,
                rpc_helper=self._anchor_rpc_helper,
                state_contract_obj=protocol_state_contract,
            )
            self._source_chain_id = await get_source_chain_id(
                redis_conn=self._redis_conn,
                rpc_helper=self._anchor_rpc_helper,
                state_contract_obj=protocol_state_contract,
            )

            self._projects_list = await get_projects_list(
                redis_conn=self._redis_conn,
                rpc_helper=self._anchor_rpc_helper,
                state_contract_obj=protocol_state_contract,
            )

            submission_window = await get_snapshot_submision_window(
                redis_conn=self._redis_conn,
                rpc_helper=self._anchor_rpc_helper,
                state_contract_obj=protocol_state_contract,
            )

            if submission_window:
                await self._redis_conn.set(
                    snapshot_submission_window_key,
                    submission_window,
                )

            # iterate over project list fetched
            for project_config in self.projects_config:
                type_ = project_config.project_type
                if project_config.projects == []:
                    relevant_projects = set(filter(lambda x: type_ in x, self._projects_list))
                    project_data = []
                    for project in relevant_projects:
                        data_source = project.split(':')[-2]
                        data_source = '_'.join(to_checksum_address(d) for d in data_source.split('_'))
                        project_data.append(
                            data_source,
                        )
                    project_config.projects = project_data

    async def _preloader_waiter(
        self,
        epoch: EpochBase,
    ):
        preloader_types_l = list(self._preload_completion_conditions[epoch.epochId].keys())
        conditions: List[Awaitable] = [
            self._preload_completion_conditions[epoch.epochId][k]
            for k in preloader_types_l
        ]
        preload_results = await asyncio.gather(
            *conditions,
            return_exceptions=True,
        )
        succesful_preloads = list()
        failed_preloads = list()
        self._logger.debug(
            'Preloading asyncio gather returned with results {}',
            preload_results,
        )
        for i, preload_result in enumerate(preload_results):
            if isinstance(preload_result, Exception):
                self._logger.error(
                    f'Preloading failed for epoch {epoch.epochId} project type {preloader_types_l[i]}',
                )
                failed_preloads.append(preloader_types_l[i])
            else:
                succesful_preloads.append(preloader_types_l[i])
                self._logger.debug(
                    'Preloading successful for preloader {}',
                    preloader_types_l[i],
                )

        self._logger.debug('Final list of successful preloads: {}', succesful_preloads)
        for project_type in self._project_type_config_mapping:
            project_config = self._project_type_config_mapping[project_type]
            if not project_config.preload_tasks:
                continue
            self._logger.debug(
                'Expected list of successful preloading for project type {}: {}',
                project_type,
                project_config.preload_tasks,
            )
            if all([t in succesful_preloads for t in project_config.preload_tasks]):
                self._logger.info(
                    'Preloading dependency satisfied for project type {} epoch {}. Distributing snapshot build tasks...',
                    project_type, epoch.epochId,
                )
                asyncio.ensure_future(
                    self._redis_conn.hset(
                        name=epoch_id_project_to_state_mapping(epoch.epochId, SnapshotterStates.PRELOAD.value),
                        mapping={
                            project_type: SnapshotterStateUpdate(
                                status='success', timestamp=int(time.time()),
                            ).json(),
                        },
                    ),
                )
                await self._distribute_callbacks_snapshotting(project_type, epoch)
            else:
                self._logger.error(
                    'Preloading dependency not satisfied for project type {} epoch {}. Not distributing snapshot build tasks...',
                    project_type, epoch.epochId,
                )
                asyncio.ensure_future(
                    self._redis_conn.hset(
                        name=epoch_id_project_to_state_mapping(epoch.epochId, SnapshotterStates.PRELOAD.value),
                        mapping={
                            project_type: SnapshotterStateUpdate(
                                status='failed', timestamp=int(time.time()),
                            ).json(),
                        },
                    ),
                )
        # TODO: set separate overall status for failed and successful preloads
        if epoch.epochId in self._preload_completion_conditions:
            del self._preload_completion_conditions[epoch.epochId]

    async def _exec_preloaders(
        self, msg_obj: EpochBase,
    ):
        """
        Functions to preload data points required by snapshot builders
        This is to save on redundant RPC and cache calls
        """
        # cleanup previous preloading complete tasks and events
        # start all preload tasks
        for preloader in preloaders:
            if preloader.task_type in self._all_preload_tasks:
                preloader_class = self._preloader_compute_mapping[preloader.task_type]
                preloader_obj = preloader_class()
                preloader_compute_kwargs = dict(
                    epoch=msg_obj,
                    redis_conn=self._redis_conn,
                    rpc_helper=self._rpc_helper,
                )
                self._logger.debug(
                    'Starting preloader obj {} for epoch {}',
                    preloader.task_type,
                    msg_obj.epochId,
                )
                f = preloader_obj.compute(**preloader_compute_kwargs)
                self._preload_completion_conditions[msg_obj.epochId][preloader.task_type] = f
        for project_config in self.projects_config:
            if not project_config.preload_tasks:
                # release for snapshotting
                asyncio.ensure_future(
                    self._distribute_callbacks_snapshotting(
                        project_config.project_type, msg_obj,
                    ),
                )
                continue

        asyncio.ensure_future(
            self._preloader_waiter(
                epoch=msg_obj,
            ),
        )

    async def _epoch_release_processor(self, message: IncomingMessage):
        try:
            msg_obj: EpochBase = (
                EpochBase.parse_raw(message.body)
            )
        except ValidationError:
            self._logger.opt(exception=True).error(
                'Bad message structure of epoch callback',
            )
            return
        except Exception:
            self._logger.opt(exception=True).error(
                'Unexpected message format of epoch callback',
            )
            return

        self._newly_added_projects = self._newly_added_projects.union(
            await self._enable_pending_projects_for_epoch(msg_obj.epochId),
        )

        asyncio.ensure_future(self._exec_preloaders(msg_obj=msg_obj))

    async def _distribute_callbacks_snapshotting(self, project_type: str, epoch: EpochBase):
        # send to snapshotters to get the balances of the addresses
        queuing_tasks = []

        async with self._rmq_channel_pool.acquire() as ch:
            # Prepare a message to send
            exchange = await ch.get_exchange(
                name=self._callback_exchange_name,
            )

            project_config = self._project_type_config_mapping[project_type]

            if project_config.projects is None:
                project_id = f'{project_type}:{settings.namespace}'
                if project_id.lower() in self._newly_added_projects:
                    genesis = True
                    self._newly_added_projects.remove(project_id.lower())
                else:
                    genesis = False
                process_unit = PowerloomSnapshotProcessMessage(
                    begin=epoch.begin,
                    end=epoch.end,
                    epochId=epoch.epochId,
                    genesis=genesis,
                )

                msg_body = Message(process_unit.json().encode('utf-8'))
                await exchange.publish(
                    routing_key=f'powerloom-backend-callback:{settings.namespace}'
                    f':{settings.instance_id}:EpochReleased.{project_type}',
                    message=msg_body,
                )
                self._logger.debug(
                    'Sent out message to be processed by worker'
                    f' {project_type} : {process_unit}',
                )
                return

            for project in project_config.projects:
                project_id = f'{project_type}:{project}:{settings.namespace}'

                if project_id.lower() in self._newly_added_projects:
                    genesis = True
                    self._newly_added_projects.remove(project_id.lower())
                else:
                    genesis = False

                data_sources = project.split('_')
                if len(data_sources) == 1:
                    data_source = data_sources[0]
                    primary_data_source = None
                else:
                    primary_data_source, data_source = data_sources
                process_unit = PowerloomSnapshotProcessMessage(
                    begin=epoch.begin,
                    end=epoch.end,
                    epochId=epoch.epochId,
                    data_source=data_source,
                    primary_data_source=primary_data_source,
                    genesis=genesis,
                )

                msg_body = Message(process_unit.json().encode('utf-8'))
                queuing_tasks.append(
                    exchange.publish(
                        routing_key=f'powerloom-backend-callback:{settings.namespace}'
                        f':{settings.instance_id}:EpochReleased.{project_type}',
                        message=msg_body,
                    ),
                )

                self._logger.debug(
                    'Sent out message to be processed by worker'
                    f' {project_type} : {process_unit}',
                )

            results = await asyncio.gather(*queuing_tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                self._logger.error(
                    'Error while sending message to queue. Error - {}',
                    result,
                )

    async def _enable_pending_projects_for_epoch(self, epoch_id) -> Set[str]:
        pending_project_msgs: List[PowerloomProjectsUpdatedMessage] = self._upcoming_project_changes.pop(epoch_id, [])
        if not pending_project_msgs:
            return set()
        else:
            for msg_obj in pending_project_msgs:
                # Update projects list
                for project_config in self.projects_config:
                    type_ = project_config.project_type
                    if type_ in msg_obj.projectId:
                        if project_config.projects is None:
                            continue
                        data_source = msg_obj.projectId.split(':')[-2]
                        data_source = '_'.join(to_checksum_address(d) for d in data_source.split('_'))
                        if msg_obj.allowed:
                            project_config.projects.append(data_source)
                            project_config.projects = list(set(project_config.projects))
                        else:
                            if data_source in project_config.projects:
                                items = set(project_config.projects)
                                items.remove(data_source)
                                project_config.projects = list(items)

        return set([msg.projectId.lower() for msg in pending_project_msgs if msg.allowed])

    async def _update_all_projects(self, message: IncomingMessage):
        event_type = message.routing_key.split('.')[-1]

        if event_type == 'ProjectsUpdated':
            msg_obj: PowerloomProjectsUpdatedMessage = (
                PowerloomProjectsUpdatedMessage.parse_raw(message.body)
            )
        else:
            return

        self._upcoming_project_changes[msg_obj.enableEpochId].append(msg_obj)

    async def _cache_and_forward_to_payload_commit_queue(self, message: IncomingMessage):
        event_type = message.routing_key.split('.')[-1]

        if event_type == 'SnapshotFinalized':
            msg_obj: PowerloomSnapshotFinalizedMessage = (
                PowerloomSnapshotFinalizedMessage.parse_raw(message.body)
            )
        else:
            return

        # Add to project finalized data zset
        await self._redis_conn.zadd(
            project_finalized_data_zset(project_id=msg_obj.projectId),
            {msg_obj.snapshotCid: msg_obj.epochId},
        )

        await self._redis_conn.hset(
            name=epoch_id_project_to_state_mapping(msg_obj.epochId, SnapshotterStates.SNAPSHOT_FINALIZE.value),
            mapping={
                msg_obj.projectId: SnapshotterStateUpdate(
                    status='success', timestamp=int(time.time()), extra={'snapshot_cid': msg_obj.snapshotCid},
                ).json(),
            },
        )

        self._logger.trace(f'Payload Commit Message Distribution time - {int(time.time())}')

        # If not initialized yet, return
        if not self._source_chain_id:
            return

        process_unit = PayloadCommitFinalizedMessage(
            message=msg_obj,
            web3Storage=True,
            sourceChainId=self._source_chain_id,
        )
        async with self._rmq_channel_pool.acquire() as channel:
            exchange = await channel.get_exchange(
                name=self._payload_commit_exchange_name,
            )
            await exchange.publish(
                routing_key=self._payload_commit_routing_key,
                message=Message(process_unit.json().encode('utf-8')),
            )

        self._logger.trace(
            (
                'Sent out Event to Payload Commit Queue'
                f' {event_type} : {process_unit}'
            ),
        )

    async def _distribute_callbacks_aggregate(self, message: IncomingMessage):
        event_type = message.routing_key.split('.')[-1]
        try:
            if event_type != 'SnapshotSubmitted':
                self._logger.error(f'Unknown event type {event_type}')
                return

            process_unit: PowerloomSnapshotSubmittedMessage = (
                PowerloomSnapshotSubmittedMessage.parse_raw(message.body)
            )

        except ValidationError:
            self._logger.opt(exception=True).error(
                'Bad message structure of event callback',
            )
            return
        except Exception:
            self._logger.opt(exception=True).error(
                'Unexpected message format of event callback',
            )
            return
        self._logger.trace(f'Aggregation Task Distribution time - {int(time.time())}')

        # go through aggregator config, if it matches then send appropriate message
        rabbitmq_publish_tasks = list()
        async with self._rmq_channel_pool.acquire() as channel:
            exchange = await channel.get_exchange(
                name=self._callback_exchange_name,
            )
            for config in aggregator_config:
                type_ = config.project_type
                if config.aggregate_on == AggregateOn.single_project:
                    if config.filters.projectId not in process_unit.projectId:
                        self._logger.trace(f'projectId mismatch {process_unit.projectId} {config.filters.projectId}')
                        continue

                    rabbitmq_publish_tasks.append(
                        exchange.publish(
                            routing_key=f'powerloom-backend-callback:{settings.namespace}:'
                            f'{settings.instance_id}:CalculateAggregate.{type_}',
                            message=Message(process_unit.json().encode('utf-8')),
                        ),
                    )
                elif config.aggregate_on == AggregateOn.multi_project:
                    if process_unit.projectId not in config.projects_to_wait_for:
                        self._logger.trace(
                            f'projectId not required for {config.project_type}: {process_unit.projectId}',
                        )
                        continue

                    # cleanup redis for all previous epochs (5 buffer)
                    await self._redis_conn.zremrangebyscore(
                        f'powerloom:aggregator:{config.project_type}:events',
                        0,
                        process_unit.epochId - 5,
                    )

                    await self._redis_conn.zadd(
                        f'powerloom:aggregator:{config.project_type}:events',
                        {process_unit.json(): process_unit.epochId},
                    )

                    events = await self._redis_conn.zrangebyscore(
                        f'powerloom:aggregator:{config.project_type}:events',
                        process_unit.epochId,
                        process_unit.epochId,
                    )

                    if not events:
                        self._logger.info(f'No events found for {process_unit.epochId}')
                        continue

                    event_project_ids = set()
                    finalized_messages = list()

                    for event in events:
                        event = PowerloomSnapshotSubmittedMessage.parse_raw(event)
                        event_project_ids.add(event.projectId)
                        finalized_messages.append(event)

                    if event_project_ids == set(config.projects_to_wait_for):
                        self._logger.info(f'All projects present for {process_unit.epochId}, aggregating')
                        final_msg = PowerloomCalculateAggregateMessage(
                            messages=finalized_messages,
                            epochId=process_unit.epochId,
                            timestamp=int(time.time()),
                        )

                        rabbitmq_publish_tasks.append(
                            exchange.publish(
                                routing_key=f'powerloom-backend-callback:{settings.namespace}'
                                f':{settings.instance_id}:CalculateAggregate.{type_}',
                                message=Message(final_msg.json().encode('utf-8')),
                            ),
                        )

                        # Cleanup redis for current epoch

                        await self._redis_conn.zremrangebyscore(
                            f'powerloom:aggregator:{config.project_type}:events',
                            process_unit.epochId,
                            process_unit.epochId,
                        )

                    else:
                        self._logger.trace(
                            f'Not all projects present for {process_unit.epochId},'
                            f' {len(set(config.projects_to_wait_for)) - len(event_project_ids)} missing',
                        )
        await asyncio.gather(*rabbitmq_publish_tasks, return_exceptions=True)

    async def _cleanup_older_epoch_status(self, epoch_id: int):
        tasks = [self._redis_conn.delete(epoch_id_epoch_released_key(epoch_id - 30))]
        delete_keys = list()
        for state in SnapshotterStates:
            k = epoch_id_project_to_state_mapping(epoch_id - 30, state.value)
            delete_keys.append(k)
        if delete_keys:
            tasks.append(self._redis_conn.delete(*delete_keys))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        await message.ack()

        message_type = message.routing_key.split('.')[-1]
        self._logger.debug(
            (
                'Got message to process and distribute: {}'
            ),
            message.body,
        )

        if message_type == 'EpochReleased':
            try:
                _: EpochBase = EpochBase.parse_raw(message.body)
            except:
                pass
            else:
                await self._redis_conn.set(
                    epoch_id_epoch_released_key(_.epochId),
                    int(time.time()),
                )
                asyncio.ensure_future(self._cleanup_older_epoch_status(_.epochId))

            _ = await self._redis_conn.get(active_status_key)
            if _:
                active_status = bool(int(_))
                if not active_status:
                    self._logger.error('System is not active, ignoring released Epoch')
                else:
                    await self._epoch_release_processor(message)

        elif message_type == 'SnapshotSubmitted':
            await self._distribute_callbacks_aggregate(
                message,
            )

        elif message_type == 'SnapshotFinalized':
            await self._cache_and_forward_to_payload_commit_queue(
                message,
            )
        elif message_type == 'ProjectsUpdated':
            await self._update_all_projects(message)
        elif message_type == 'allSnapshottersUpdated':
            msg_cast = SnapshottersUpdatedEvent.parse_raw(message.body)
            if msg_cast.snapshotterAddress == to_checksum_address(settings.instance_id):
                if self._redis_conn:
                    await self._redis_conn.set(
                        active_status_key,
                        int(msg_cast.allowed),
                    )
        else:
            self._logger.error(
                (
                    'Unknown routing key for callback distribution: {}'
                ),
                message.routing_key,
            )

        if self._redis_conn:
            await self._redis_conn.close()

    async def _rabbitmq_consumer(self, loop):
        async with self._rmq_channel_pool.acquire() as channel:
            await channel.set_qos(10)
            exchange = await channel.get_exchange(
                name=self._consume_exchange_name,
            )
            q_obj = await channel.get_queue(
                name=self._consume_queue_name,
                ensure=False,
            )
            self._logger.debug(
                f'Consuming queue {self._consume_queue_name} with routing key {self._consume_queue_routing_key}...',
            )
            await q_obj.bind(exchange, routing_key=self._consume_queue_routing_key)
            await q_obj.consume(self._on_rabbitmq_message)

    def run(self) -> None:
        self._logger = logger.bind(
            module=f'Powerloom|Callbacks|ProcessDistributor:{settings.namespace}-{settings.instance_id}',
        )
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        ev_loop = asyncio.get_event_loop()
        ev_loop.run_until_complete(self.init_worker())

        self._logger.debug('Starting RabbitMQ consumer on queue {} for Processor Distributor', self._consume_queue_name)
        self._core_rmq_consumer = asyncio.ensure_future(
            self._rabbitmq_consumer(ev_loop),
        )
        try:
            ev_loop.run_forever()
        finally:
            ev_loop.close()
