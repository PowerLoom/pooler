import asyncio
import importlib
import json
import multiprocessing
import queue
import resource
import time
from collections import defaultdict
from functools import partial
from signal import SIGINT
from signal import signal
from signal import SIGQUIT
from signal import SIGTERM
from typing import Awaitable
from typing import Dict
from typing import List
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
from snapshotter.utils.data_utils import get_snapshot_submision_window
from snapshotter.utils.data_utils import get_source_chain_epoch_size
from snapshotter.utils.data_utils import get_source_chain_id
from snapshotter.utils.default_logger import logger
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.models.data_models import SnapshotterStates
from snapshotter.utils.models.data_models import SnapshotterStateUpdate
from snapshotter.utils.models.data_models import SnapshottersUpdatedEvent
from snapshotter.utils.models.message_models import EpochBase
from snapshotter.utils.models.message_models import PowerloomCalculateAggregateMessage
from snapshotter.utils.models.message_models import PowerloomProjectTypeProcessingCompleteMessage
from snapshotter.utils.models.message_models import PowerloomSnapshotFinalizedMessage
from snapshotter.utils.models.message_models import PowerloomSnapshotProcessMessage
from snapshotter.utils.models.settings_model import AggregationConfigMulti
from snapshotter.utils.models.settings_model import AggregationConfigSingle
from snapshotter.utils.redis.redis_conn import RedisPoolCache
from snapshotter.utils.redis.redis_keys import active_status_key
from snapshotter.utils.redis.redis_keys import epoch_id_epoch_released_key
from snapshotter.utils.redis.redis_keys import epoch_id_project_to_state_mapping
from snapshotter.utils.redis.redis_keys import project_finalized_data_zset
from snapshotter.utils.redis.redis_keys import project_last_finalized_epoch_key
from snapshotter.utils.redis.redis_keys import snapshot_submission_window_key
from snapshotter.utils.rpc import RpcHelper


class ProcessorDistributor(multiprocessing.Process):
    _aioredis_pool: RedisPoolCache
    _redis_conn: aioredis.Redis
    _anchor_rpc_helper: RpcHelper
    _async_transport: AsyncHTTPTransport
    _client: AsyncClient

    def __init__(self, name, **kwargs):
        """
        Initialize the ProcessorDistributor object.

        Args:
            name (str): The name of the ProcessorDistributor.
            **kwargs: Additional keyword arguments.

        Attributes:
            _unique_id (str): The unique ID of the ProcessorDistributor.
            _q (queue.Queue): The queue used for processing tasks.
            _rabbitmq_interactor: The RabbitMQ interactor object.
            _shutdown_initiated (bool): Flag indicating if shutdown has been initiated.
            _rpc_helper: The RPC helper object.
            _source_chain_id: The source chain ID.
            _projects_list: The list of projects.
            _consume_exchange_name (str): The name of the exchange for consuming events.
            _consume_queue_name (str): The name of the queue for consuming events.
            _initialized (bool): Flag indicating if the ProcessorDistributor has been initialized.
            _consume_queue_routing_key (str): The routing key for consuming events.
            _callback_exchange_name (str): The name of the exchange for callbacks.
            _upcoming_project_changes (defaultdict): Dictionary of upcoming project changes.
            _preload_completion_conditions (defaultdict): Dictionary of preload completion conditions.
            _shutdown_initiated (bool): Flag indicating if shutdown has been initiated.
            _all_preload_tasks (set): Set of all preload tasks.
            _project_type_config_mapping (dict): Dictionary mapping project types to their configurations.
            _preloader_compute_mapping (dict): Dictionary mapping preloader tasks to compute resources.
        """
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
        self._upcoming_project_changes = defaultdict(list)
        self._preload_completion_conditions: Dict[int, Dict] = defaultdict(
            dict,
        )  # epoch ID to preloading complete event

        self._shutdown_initiated = False
        self._all_preload_tasks = set()
        self._project_type_config_mapping = dict()
        for project_config in projects_config:
            self._project_type_config_mapping[project_config.project_type] = project_config
            for proload_task in project_config.preload_tasks:
                self._all_preload_tasks.add(proload_task)
        self._preloader_compute_mapping = dict()

    def _signal_handler(self, signum, frame):
        """
        Signal handler method that cancels the core RMQ consumer when a SIGINT, SIGTERM, or SIGQUIT signal is received.

        Args:
            signum (int): The signal number.
            frame (frame): The current stack frame at the time the signal was received.
        """

        if signum in [SIGINT, SIGTERM, SIGQUIT]:
            self._core_rmq_consumer.cancel()

    async def _init_redis_pool(self):
        """
        Initializes the Redis connection pool and populates it with connections.
        """
        self._aioredis_pool = RedisPoolCache()
        await self._aioredis_pool.populate()
        self._redis_conn = self._aioredis_pool._aioredis_pool

    async def _init_rpc_helper(self):
        """
        Initializes the RpcHelper instance if it is not already initialized.
        """
        if not self._rpc_helper:
            self._rpc_helper = RpcHelper()
            self._anchor_rpc_helper = RpcHelper(rpc_settings=settings.anchor_chain_rpc)

    async def _init_rabbitmq_connection(self):
        """
        Initializes the RabbitMQ connection pool and channel pool.

        The RabbitMQ connection pool is used to manage a pool of connections to the RabbitMQ server,
        while the channel pool is used to manage a pool of channels for each connection.

        Returns:
            None
        """
        self._rmq_connection_pool = Pool(
            get_rabbitmq_robust_connection_async,
            max_size=20, loop=asyncio.get_event_loop(),
        )
        self._rmq_channel_pool = Pool(
            partial(get_rabbitmq_channel, self._rmq_connection_pool), max_size=100,
            loop=asyncio.get_event_loop(),
        )

    async def _init_httpx_client(self):
        """
        Initializes the HTTPX client with the specified settings.
        """
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

    async def _init_preloader_compute_mapping(self):
        """
        Initializes the preloader compute mapping by importing the preloader module and class and
        adding it to the mapping dictionary.
        """
        if self._preloader_compute_mapping:
            return

        for preloader in preloaders:
            if preloader.task_type in self._all_preload_tasks:
                preloader_module = importlib.import_module(preloader.module)
                preloader_class = getattr(preloader_module, preloader.class_name)
                self._preloader_compute_mapping[preloader.task_type] = preloader_class

    async def init_worker(self):
        """
        Initializes the worker by initializing the Redis pool, RPC helper, loading project metadata,
        initializing the RabbitMQ connection, and initializing the preloader compute mapping.
        """
        if not self._initialized:
            await self._init_redis_pool()
            await self._init_httpx_client()
            await self._init_rpc_helper()
            await self._load_projects_metadata()
            await self._init_rabbitmq_connection()
            await self._init_preloader_compute_mapping()
            self._initialized = True

    async def _load_projects_metadata(self):
        """
        Loads the metadata for the projects, including the source chain ID, the list of projects, and the submission window
        for snapshots. It also updates the project type configuration mapping with the relevant projects.
        """
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

    async def _preloader_waiter(
        self,
        epoch: EpochBase,
    ):
        """
        Wait for all preloading tasks to complete for the given epoch, and distribute snapshot build tasks if all preloading
        dependencies are satisfied.

        Args:
            epoch: The epoch for which to wait for preloading tasks to complete.

        Returns:
            None
        """

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
        Executes preloading tasks for the given epoch object.

        Args:
            msg_obj (EpochBase): The epoch object for which preloading tasks need to be executed.

        Returns:
            None
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

        for project_type, project_config in self._project_type_config_mapping.items():
            if not project_config.preload_tasks:
                # release for snapshotting
                asyncio.ensure_future(
                    self._distribute_callbacks_snapshotting(
                        project_type, msg_obj,
                    ),
                )
                continue

        asyncio.ensure_future(
            self._preloader_waiter(
                epoch=msg_obj,
            ),
        )

    async def _epoch_release_processor(self, message: IncomingMessage):
        """
        This method is called when an epoch is released. It enables pending projects for the epoch and executes preloaders.

        Args:
            message (IncomingMessage): The message containing the epoch information.
        """
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

        asyncio.ensure_future(self._exec_preloaders(msg_obj=msg_obj))

    async def _distribute_callbacks_snapshotting(self, project_type: str, epoch: EpochBase):
        """
        Distributes callbacks for snapshotting to the appropriate snapshotters based on the project type and epoch.

        Args:
            project_type (str): The type of project.
            epoch (EpochBase): The epoch to snapshot.

        Returns:
            None
        """

        async with self._rmq_channel_pool.acquire() as ch:
            # Prepare a message to send
            exchange = await ch.get_exchange(
                name=self._callback_exchange_name,
            )

            process_unit = PowerloomSnapshotProcessMessage(
                begin=epoch.begin,
                end=epoch.end,
                epochId=epoch.epochId,
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

    async def _handle_snapshot_finalized_message(self, message: IncomingMessage):
        """
        Handles the SnapshotFinalized message.

        Args:
            message (IncomingMessage): The incoming message object.

        Returns:
            None
        """
        event_type = message.routing_key.split('.')[-1]

        if event_type == 'SnapshotFinalized':
            msg_obj: PowerloomSnapshotFinalizedMessage = (
                PowerloomSnapshotFinalizedMessage.parse_raw(message.body)
            )
        else:
            return

        # set project last finalized epoch in redis
        await self._redis_conn.set(
            project_last_finalized_epoch_key(msg_obj.projectId),
            msg_obj.epochId,
        )

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

    async def _distribute_callbacks_aggregate(self, message: IncomingMessage):
        """
        Distributes the callbacks for aggregation.

        :param message: IncomingMessage object containing the message to be processed.
        """
        try:
            process_unit: PowerloomProjectTypeProcessingCompleteMessage = (
                PowerloomProjectTypeProcessingCompleteMessage.parse_raw(message.body)
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
                task_type = config.project_type

                if type(config) == AggregationConfigSingle:
                    if config.filters.project_type == process_unit.projectType:
                        rabbitmq_publish_tasks.append(
                            exchange.publish(
                                routing_key=f'powerloom-backend-callback:{settings.namespace}:'
                                f'{settings.instance_id}:CalculateAggregate.{task_type}',
                                message=Message(process_unit.json().encode('utf-8')),
                            ),
                        )

                elif type(config) == AggregationConfigMulti:
                    if process_unit.projectType not in config.project_types_to_wait_for:
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

                    event_project_types = set()
                    finalized_messages = list()

                    for event in events:
                        event = PowerloomProjectTypeProcessingCompleteMessage.parse_raw(event)
                        event_project_types.add(event.projectType)
                        finalized_messages.append(event)

                    if event_project_types == set(config.project_types_to_wait_for):
                        self._logger.info(f'All projects present for {process_unit.epochId}, aggregating')
                        final_msg = PowerloomCalculateAggregateMessage(
                            messages=finalized_messages,
                            epochId=process_unit.epochId,
                            timestamp=int(time.time()),
                        )

                        rabbitmq_publish_tasks.append(
                            exchange.publish(
                                routing_key=f'powerloom-backend-callback:{settings.namespace}'
                                f':{settings.instance_id}:CalculateAggregate.{task_type}',
                                message=Message(final_msg.json().encode('utf-8')),
                            ),
                        )

                        # Cleanup redis for current epoch

                        await self._redis_conn.zremrangebyscore(
                            f'powerloom:aggregator:{config.project_type}:events',
                            process_unit.epochId,
                            process_unit.epochId,
                        )

        if not rabbitmq_publish_tasks:
            self._logger.info(f'No aggregators found for {process_unit.projectType}')
            return

        await asyncio.gather(*rabbitmq_publish_tasks, return_exceptions=True)

    async def _cleanup_older_epoch_status(self, epoch_id: int):
        """
        Deletes the epoch status keys for the epoch that is 30 epochs older than the given epoch_id.
        """
        tasks = [self._redis_conn.delete(epoch_id_epoch_released_key(epoch_id - 30))]
        delete_keys = list()
        for state in SnapshotterStates:
            k = epoch_id_project_to_state_mapping(epoch_id - 30, state.value)
            delete_keys.append(k)
        if delete_keys:
            tasks.append(self._redis_conn.delete(*delete_keys))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        """
        Callback function to handle incoming RabbitMQ messages.

        Args:
            message (IncomingMessage): The incoming RabbitMQ message.

        Returns:
            None
        """
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

            _is_snapshotter_active = await self._redis_conn.get(active_status_key)
            if _is_snapshotter_active:
                active_status = bool(int(_is_snapshotter_active))
                if not active_status:
                    self._logger.error('System is not active, ignoring released Epoch')
                else:
                    await self._epoch_release_processor(message)

        elif message_type == 'ProjectTypeProcessingComplete':
            await self._distribute_callbacks_aggregate(
                message,
            )

        elif message_type == 'SnapshotFinalized':
            await self._handle_snapshot_finalized_message(
                message,
            )

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
                message_type,
            )

        if self._redis_conn:
            await self._redis_conn.close()

    async def _rabbitmq_consumer(self, loop):
        """
        Consume messages from a RabbitMQ queue.

        Args:
            loop: The event loop to use for the consumer.

        Returns:
            None
        """
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
        """
        Runs the ProcessorDistributor by setting resource limits, registering signal handlers,
        initializing the worker, starting the RabbitMQ consumer, and running the event loop.
        """
        self._logger = logger.bind(
            module=f'Powerloom|Callbacks|ProcessDistributor:{settings.namespace}-{settings.instance_id}',
        )
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (settings.rlimit.file_descriptors, hard),
        )
        for signame in [SIGINT, SIGTERM, SIGQUIT]:
            signal(signame, self._signal_handler)
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        self._anchor_rpc_helper = RpcHelper(
            rpc_settings=settings.anchor_chain_rpc,
        )
        self._anchor_rpc_helper._load_web3_providers_and_rate_limits()
        protocol_abi = read_json_file(settings.protocol_state.abi, self._logger)
        self._protocol_state_contract = self._anchor_rpc_helper.get_current_node()['web3_client'].eth.contract(
            address=to_checksum_address(
                settings.protocol_state.address,
            ),
            abi=protocol_abi,
        )
        try:
            source_block_time = self._protocol_state_contract.functions.SOURCE_CHAIN_BLOCK_TIME().call()
        except Exception as e:
            self._logger.exception(
                'Exception in querying protocol state for source chain block time: {}',
                e,
            )
        else:
            self._source_chain_block_time = source_block_time / 10 ** 4
            self._logger.debug('Set source chain block time to {}', self._source_chain_block_time)

        try:
            epoch_size = self._protocol_state_contract.functions.EPOCH_SIZE().call()
        except Exception as e:
            self._logger.exception(
                'Exception in querying protocol state for epoch size: {}',
                e,
            )
        else:
            self._epoch_size = epoch_size
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
