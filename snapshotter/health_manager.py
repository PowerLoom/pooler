import asyncio
import json
import multiprocessing
import resource
import time
from datetime import datetime
from functools import partial

import uvloop
from aio_pika import Message
from aio_pika.pool import Pool
from httpx import AsyncClient
from httpx import AsyncHTTPTransport
from httpx import Limits
from httpx import Timeout
from redis import asyncio as aioredis

from snapshotter.settings.config import settings
from snapshotter.utils.callback_helpers import get_rabbitmq_channel
from snapshotter.utils.callback_helpers import get_rabbitmq_robust_connection_async
from snapshotter.utils.callback_helpers import send_failure_notifications_async
from snapshotter.utils.default_logger import logger
from snapshotter.utils.models.data_models import SnapshotterEpochProcessingReportItem
from snapshotter.utils.models.data_models import SnapshotterIssue
from snapshotter.utils.models.data_models import SnapshotterReportState
from snapshotter.utils.models.data_models import SnapshotterStates
from snapshotter.utils.models.data_models import SnapshotterStateUpdate
from snapshotter.utils.models.message_models import ProcessHubCommand
from snapshotter.utils.redis.redis_conn import RedisPoolCache
from snapshotter.utils.redis.redis_keys import epoch_id_project_to_state_mapping
from snapshotter.utils.redis.redis_keys import last_epoch_detected_epoch_id_key
from snapshotter.utils.redis.redis_keys import last_epoch_detected_timestamp_key
from snapshotter.utils.redis.redis_keys import last_snapshot_processing_complete_timestamp_key
from snapshotter.utils.redis.redis_keys import process_hub_core_start_timestamp


class HealthManager(multiprocessing.Process):
    _aioredis_pool: RedisPoolCache
    _redis_conn: aioredis.Redis
    _async_transport: AsyncHTTPTransport
    _client: AsyncClient

    def __init__(self, name, **kwargs):
        """
        Initialize the HealthManager object.

        Args:
            name (str): The name of the HealthManager.
            **kwargs: Additional keyword arguments.

        Attributes:
            _rabbitmq_interactor: The RabbitMQ interactor object.
            _shutdown_initiated (bool): Flag indicating if shutdown has been initiated.
            _initialized (bool): Flag indicating if the HealthManager has been initialized.
            _shutdown_initiated (bool): Flag indicating if shutdown has been initiated.
            _last_epoch_processing_health_check (int): Timestamp of the last epoch processing health check.
        """
        super(HealthManager, self).__init__(name=name, **kwargs)
        self._rabbitmq_interactor = None
        self._shutdown_initiated = False
        self._initialized = False

        self._shutdown_initiated = False
        self._last_epoch_processing_health_check = 0

    async def _init_redis_pool(self):
        """
        Initializes the Redis connection pool and populates it with connections.
        """
        self._aioredis_pool = RedisPoolCache()
        await self._aioredis_pool.populate()
        self._redis_conn = self._aioredis_pool._aioredis_pool

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
            max_size=2, loop=asyncio.get_event_loop(),
        )
        self._rmq_channel_pool = Pool(
            partial(get_rabbitmq_channel, self._rmq_connection_pool), max_size=10,
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

    async def _send_proc_hub_respawn(self):
        """
        Sends a respawn command to the process hub.

        This method creates a ProcessHubCommand object with the command 'respawn',
        acquires a channel from the channel pool, gets the exchange, and publishes
        the command message to the exchange.

        Args:
            None

        Returns:
            None
        """
        proc_hub_cmd = ProcessHubCommand(
            command='respawn',
        )
        async with self._rmq_channel_pool.acquire() as channel:
            exchange = await channel.get_exchange(
                name=f'{settings.rabbitmq.setup.core.exchange}:{settings.namespace}',
            )
            await exchange.publish(
                routing_key=f'processhub-commands:{settings.namespace}:{settings.instance_id}',
                message=Message(proc_hub_cmd.json().encode('utf-8')),
            )

    async def init_worker(self):
        """
        Initializes the worker by initializing the Redis pool, RPC helper, loading project metadata,
        initializing the RabbitMQ connection, and initializing the preloader compute mapping.
        """
        if not self._initialized:
            await self._init_redis_pool()
            await self._init_httpx_client()
            await self._init_rabbitmq_connection()
            self._initialized = True

    async def _get_proc_hub_start_time(self) -> int:
        """
        Retrieves the start time of the process hub core from Redis.

        Returns:
            int: The start time of the process hub core, or 0 if not found.
        """
        _ = await self._redis_conn.get(process_hub_core_start_timestamp())
        if _:
            return int(_)
        else:
            return 0

    async def _epoch_processing_health_check(self, current_epoch_id):
        """
        Perform health check for epoch processing.

        Args:
            current_epoch_id (int): The current epoch ID.

        Returns:
            None
        """
        # TODO: make the threshold values configurable.
        # Range of epochs to be checked, success percentage/criteria, offset from current epoch
        if current_epoch_id < 5:
            return
        # get last set start time by proc hub core
        start_time = await self._get_proc_hub_start_time()

        # only start if 5 minutes have passed since proc hub core start time
        if int(time.time()) - start_time < 5 * 60:
            self._logger.info(
                'Skipping epoch processing health check because 5 minutes have not passed since proc hub core start time',
            )
            return

        if start_time == 0:
            self._logger.info('Skipping epoch processing health check because proc hub start time is not set')
            return

        # only runs once every minute
        if self._last_epoch_processing_health_check != 0 and int(time.time()) - self._last_epoch_processing_health_check < 60:
            self._logger.debug(
                'Skipping epoch processing health check because it was run less than a minute ago',
            )
            return

        self._last_epoch_processing_health_check = int(time.time())

        last_epoch_detected = await self._redis_conn.get(last_epoch_detected_timestamp_key())
        last_snapshot_processed = await self._redis_conn.get(last_snapshot_processing_complete_timestamp_key())

        if last_epoch_detected:
            last_epoch_detected = int(last_epoch_detected)

        if last_snapshot_processed:
            last_snapshot_processed = int(last_snapshot_processed)

        # if no epoch is detected for 5 minutes, report unhealthy and send respawn command
        if last_epoch_detected and int(time.time()) - last_epoch_detected > 5 * 60:
            self._logger.debug(
                'Sending unhealthy epoch report to reporting service due to no epoch detected for ~30 epochs',
            )
            await send_failure_notifications_async(
                client=self._client,
                message=SnapshotterIssue(
                    instanceID=settings.instance_id,
                    issueType=SnapshotterReportState.UNHEALTHY_EPOCH_PROCESSING.value,
                    projectID='',
                    epochId='',
                    timeOfReporting=datetime.now().isoformat(),
                    extra=json.dumps(
                        {
                            'last_epoch_detected': last_epoch_detected,
                        },
                    ),
                ),
            )
            self._logger.info(
                'Sending respawn command for all process hub core children because no epoch was detected for ~30 epochs',
            )
            await self._send_proc_hub_respawn()

        # if time difference between last epoch detected and last snapshot processed
        # is more than 5 minutes, report unhealthy and send respawn command
        if last_epoch_detected and last_snapshot_processed and \
                last_epoch_detected - last_snapshot_processed > 5 * 60:
            self._logger.debug(
                'Sending unhealthy epoch report to reporting service due to no snapshot processing for ~30 epochs',
            )
            await send_failure_notifications_async(
                client=self._client,
                message=SnapshotterIssue(
                    instanceID=settings.instance_id,
                    issueType=SnapshotterReportState.UNHEALTHY_EPOCH_PROCESSING.value,
                    projectID='',
                    epochId='',
                    timeOfReporting=datetime.now().isoformat(),
                    extra=json.dumps(
                        {
                            'last_epoch_detected': last_epoch_detected,
                            'last_snapshot_processed': last_snapshot_processed,
                        },
                    ),
                ),
            )
            self._logger.info(
                'Sending respawn command for all process hub core children because no snapshot processing was done for ~30 epochs',
            )
            await self._send_proc_hub_respawn()

            # check for epoch processing status
            epoch_health = dict()
            # check from previous epoch processing status until 2 further epochs
            build_state_val = SnapshotterStates.SNAPSHOT_BUILD.value
            for epoch_id in range(current_epoch_id - 1, current_epoch_id - 3 - 1, -1):
                epoch_specific_report = SnapshotterEpochProcessingReportItem.construct()
                success_percentage = 0
                epoch_specific_report.epochId = epoch_id
                state_report_entries = await self._redis_conn.hgetall(
                    name=epoch_id_project_to_state_mapping(epoch_id=epoch_id, state_id=build_state_val),
                )
                if state_report_entries:
                    project_state_report_entries = {
                        project_id.decode('utf-8'): SnapshotterStateUpdate.parse_raw(project_state_entry)
                        for project_id, project_state_entry in state_report_entries.items()
                    }
                    epoch_specific_report.transitionStatus[build_state_val] = project_state_report_entries
                    success_percentage += len(
                        [
                            project_state_report_entry
                            for project_state_report_entry in project_state_report_entries.values()
                            if project_state_report_entry.status == 'success'
                        ],
                    ) / len(project_state_report_entries)

                if any([x is None for x in epoch_specific_report.transitionStatus.values()]):
                    epoch_health[epoch_id] = False
                    self._logger.debug(
                        'Marking epoch {} as unhealthy due to missing state reports against transitions {}',
                        epoch_id,
                        [x for x, y in epoch_specific_report.transitionStatus.items() if y is None],
                    )
                if success_percentage < 0.5 and success_percentage != 0:
                    epoch_health[epoch_id] = False
                    self._logger.debug(
                        'Marking epoch {} as unhealthy due to low success percentage: {}',
                        epoch_id,
                        success_percentage,
                    )
            if len([epoch_id for epoch_id, healthy in epoch_health.items() if not healthy]) >= 2:
                self._logger.debug(
                    'Sending unhealthy epoch report to reporting service: {}',
                    epoch_health,
                )
                await send_failure_notifications_async(
                    client=self._client,
                    message=SnapshotterIssue(
                        instanceID=settings.instance_id,
                        issueType=SnapshotterReportState.UNHEALTHY_EPOCH_PROCESSING.value,
                        projectID='',
                        epochId='',
                        timeOfReporting=datetime.now().isoformat(),
                        extra=json.dumps(
                            {
                                'epoch_health': epoch_health,
                            },
                        ),
                    ),
                )
                self._logger.info(
                    'Sending respawn command for all process hub core children because epochs were found unhealthy: {}', epoch_health,
                )
                await self._send_proc_hub_respawn()

    async def _check_health(self, loop):
        # will do constant health checks and send respawn command if unhealthy
        while True:
            await asyncio.sleep(60)
            if self._shutdown_initiated:
                break

            last_detected_epoch = await self._redis_conn.get(last_epoch_detected_epoch_id_key())
            if last_detected_epoch:
                last_detected_epoch = int(last_detected_epoch)
                asyncio.ensure_future(self._epoch_processing_health_check(last_detected_epoch))

    def run(self) -> None:
        """
        Runs the HealthManager by setting resource limits, registering signal handlers,
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
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

        ev_loop = asyncio.get_event_loop()
        ev_loop.run_until_complete(self.init_worker())

        self._logger.debug('Staring Health Manager')
        asyncio.ensure_future(
            self._check_health(ev_loop),
        )
        try:
            ev_loop.run_forever()
        finally:
            ev_loop.close()


if __name__ == '__main__':
    health_manager = HealthManager('HealthManager')
    health_manager.run()
