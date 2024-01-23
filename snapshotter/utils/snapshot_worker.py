import asyncio
import importlib
import json
import time
from typing import Optional

from aio_pika import IncomingMessage
from aio_pika import Message
from ipfs_client.main import AsyncIPFSClient
from ipfs_client.main import AsyncIPFSClientSingleton
from pydantic import ValidationError

from snapshotter.settings.config import projects_config
from snapshotter.settings.config import settings
from snapshotter.utils.callback_helpers import send_failure_notifications_async
from snapshotter.utils.generic_worker import GenericAsyncWorker
from snapshotter.utils.models.data_models import SnapshotterIssue
from snapshotter.utils.models.data_models import SnapshotterReportState
from snapshotter.utils.models.data_models import SnapshotterStates
from snapshotter.utils.models.data_models import SnapshotterStateUpdate
from snapshotter.utils.models.message_models import ProjectTypeProcessingCompleteMessage
from snapshotter.utils.models.message_models import SnapshotProcessMessage
from snapshotter.utils.models.message_models import SnapshotSubmittedMessageLite
from snapshotter.utils.redis.rate_limiter import load_rate_limiter_scripts
from snapshotter.utils.redis.redis_keys import epoch_id_project_to_state_mapping
from snapshotter.utils.redis.redis_keys import last_snapshot_processing_complete_timestamp_key
from snapshotter.utils.redis.redis_keys import snapshot_submission_window_key
from snapshotter.utils.redis.redis_keys import submitted_base_snapshots_key


class SnapshotAsyncWorker(GenericAsyncWorker):
    _ipfs_singleton: AsyncIPFSClientSingleton
    _ipfs_writer_client: AsyncIPFSClient
    _ipfs_reader_client: AsyncIPFSClient

    def __init__(self, name, **kwargs):
        """
        Initializes a SnapshotAsyncWorker object.

        Args:
            name (str): The name of the worker.
            **kwargs: Additional keyword arguments to be passed to the AsyncWorker constructor.
        """
        self._q = f'backend-cb-snapshot:{settings.namespace}:{settings.instance_id}'
        self._rmq_routing = f'backend-callback:{settings.namespace}:{settings.instance_id}:EpochReleased.*'
        super(SnapshotAsyncWorker, self).__init__(name=name, **kwargs)
        self._project_calculation_mapping = {}
        self._task_types = []
        for project_config in projects_config:
            task_type = project_config.project_type
            self._task_types.append(task_type)
        self._submission_window = 0

    def _gen_project_id(self, task_type: str, data_source: Optional[str] = None, primary_data_source: Optional[str] = None):
        """
        Generates a project ID based on the given task type, data source, and primary data source.

        Args:
            task_type (str): The type of task.
            data_source (Optional[str], optional): The data source. Defaults to None.
            primary_data_source (Optional[str], optional): The primary data source. Defaults to None.

        Returns:
            str: The generated project ID.
        """
        if not data_source:
            # For generic use cases that don't have a data source like block details
            project_id = f'{task_type}:{settings.namespace}'
        else:
            if primary_data_source:
                project_id = f'{task_type}:{primary_data_source.lower()}_{data_source.lower()}:{settings.namespace}'
            else:
                project_id = f'{task_type}:{data_source.lower()}:{settings.namespace}'
        return project_id

    async def _process(self, msg_obj: SnapshotProcessMessage, task_type: str):
        """
        Processes the given SnapshotProcessMessage object in bulk mode.

        Args:
            msg_obj (SnapshotProcessMessage): The message object to process.
            task_type (str): The type of task to perform.

        Raises:
            Exception: If an error occurs while processing the message.

        Returns:
            None
        """
        try:
            task_processor = self._project_calculation_mapping[task_type]

            snapshots = await task_processor.compute(
                msg_obj=msg_obj,
                redis=self._redis_conn,
                rpc_helper=self._rpc_helper,
                anchor_rpc_helper=self._anchor_rpc_helper,
                ipfs_reader=self._ipfs_reader_client,
                protocol_state_contract=self._protocol_state_contract,
            )

            if not snapshots:
                self._logger.debug(
                    'No snapshot data for: {}, skipping...', msg_obj,
                )

        except Exception as e:
            self._logger.opt(exception=True).error(
                'Exception processing callback for epoch: {}, Error: {},'
                'sending failure notifications', msg_obj, e,
            )

            notification_message = SnapshotterIssue(
                instanceID=settings.instance_id,
                issueType=SnapshotterReportState.MISSED_SNAPSHOT.value,
                projectID=f'{task_type}:{settings.namespace}',
                epochId=str(msg_obj.epochId),
                timeOfReporting=str(time.time()),
                extra=json.dumps({'issueDetails': f'Error : {e}'}),
            )

            await send_failure_notifications_async(
                client=self._client, message=notification_message,
            )

            await self._redis_conn.hset(
                name=epoch_id_project_to_state_mapping(
                    epoch_id=msg_obj.epochId, state_id=SnapshotterStates.SNAPSHOT_BUILD.value,
                ),
                mapping={
                    f'{task_type}:{settings.namespace}': SnapshotterStateUpdate(
                        status='failed', error=str(e), timestamp=int(time.time()),
                    ).json(),
                },
            )
        else:

            await self._redis_conn.set(
                name=last_snapshot_processing_complete_timestamp_key(),
                value=int(time.time()),
            )

            if not snapshots:
                self._logger.debug(
                    'No snapshot data for: {}, skipping...', msg_obj,
                )
                return

            self._logger.info('Sending snapshots to commit service: {}', snapshots)
            submitted_snapshots = []

            for project_data_source, snapshot in snapshots:

                data_sources = project_data_source.split('_')
                if len(data_sources) == 1:
                    data_source = data_sources[0]
                    primary_data_source = None
                else:
                    primary_data_source, data_source = data_sources

                project_id = self._gen_project_id(
                    task_type=task_type, data_source=data_source, primary_data_source=primary_data_source,
                )

                await self._redis_conn.set(
                    name=submitted_base_snapshots_key(
                        epoch_id=msg_obj.epochId, project_id=project_id,
                    ),
                    value=snapshot.json(),
                    # block time is about 2 seconds on anchor chain, keeping it around ten times the submission window
                    ex=self._submission_window * 10 * 2,
                )
                p = self._redis_conn.pipeline()
                p.hset(
                    name=epoch_id_project_to_state_mapping(
                        epoch_id=msg_obj.epochId, state_id=SnapshotterStates.SNAPSHOT_BUILD.value,
                    ),
                    mapping={
                        project_id: SnapshotterStateUpdate(
                            status='success', timestamp=int(time.time()),
                        ).json(),
                    },
                )
                await p.execute()
                snapshot_cid = await self._commit_payload(
                    task_type=task_type,
                    _ipfs_writer_client=self._ipfs_writer_client,
                    project_id=project_id,
                    epoch=msg_obj,
                    snapshot=snapshot,
                    storage_flag=settings.web3storage.upload_snapshots,
                )

                submitted_snapshots.append((project_id, snapshot_cid))

            # publish snapshot submitted event to event detector queue
            processing_complete_message = ProjectTypeProcessingCompleteMessage(
                epochId=msg_obj.epochId,
                projectType=task_type,
                snapshotsSubmitted=[
                    SnapshotSubmittedMessageLite(
                        snapshotCid=snapshot_cid,
                        projectId=project_id,
                    ) for project_id, snapshot_cid in submitted_snapshots
                ],
            )

            try:
                async with self._rmq_connection_pool.acquire() as connection:
                    async with self._rmq_channel_pool.acquire() as channel:
                        # Prepare a message to send
                        event_detector_exchange = await channel.get_exchange(
                            name=self._event_detector_exchange,
                        )
                        message_data = processing_complete_message.json().encode()

                        # Prepare a message to send
                        message = Message(message_data)

                        await event_detector_exchange.publish(
                            message=message,
                            routing_key=self._event_detector_routing_key_prefix + 'ProjectTypeProcessingComplete',
                        )

                        self._logger.debug(
                            'Sent project type processing complete message to event detector queue: {} | Project Type: {} | Epoch: {}',
                            processing_complete_message, task_type, msg_obj.epochId,
                        )

            except Exception as e:
                self._logger.opt(exception=True).error(
                    'Error publishing project type processing complete message to event detector queue: {} | Project Type: {} | Epoch: {}',
                    processing_complete_message, task_type, msg_obj.epochId,
                )

    async def _processor_task(self, msg_obj: SnapshotProcessMessage, task_type: str):
        """
        Process a SnapshotProcessMessage object for a given task type.

        Args:
            msg_obj (SnapshotProcessMessage): The message object to process.
            task_type (str): The type of task to perform.

        Returns:
            None
        """
        self._logger.debug(
            'Processing callback: {}', msg_obj,
        )
        if task_type not in self._project_calculation_mapping:
            self._logger.error(
                (
                    'No project calculation mapping found for task type'
                    f' {task_type}. Skipping...'
                ),
            )
            return

        if not self._submission_window:
            submission_window = await self._redis_conn.get(
                name=snapshot_submission_window_key,
            )
            if submission_window:
                self._submission_window = int(submission_window)

        if not self._rate_limiting_lua_scripts:
            self._rate_limiting_lua_scripts = await load_rate_limiter_scripts(
                self._redis_conn,
            )
        self._logger.debug(
            'Got epoch to process for {}: {}',
            task_type, msg_obj,
        )

        await self._process(msg_obj=msg_obj, task_type=task_type)
        await self._redis_conn.close()

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        """
        Callback function that is called when a message is received from RabbitMQ.
        It processes the message and starts the processor task.

        Args:
            message (IncomingMessage): The incoming message from RabbitMQ.

        Returns:
            None
        """
        if not message.routing_key:
            return

        task_type = message.routing_key.split('.')[-1]
        if task_type not in self._task_types:
            return

        await message.ack()

        await self.init_worker()

        self._logger.debug('task type: {}', task_type)

        try:
            msg_obj: SnapshotProcessMessage = (
                SnapshotProcessMessage.parse_raw(message.body)
            )
        except ValidationError as e:
            self._logger.opt(exception=True).error(
                (
                    'Bad message structure of callback processor. Error: {}, {}'
                ),
                e, message.body,
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

    async def _init_project_calculation_mapping(self):
        """
        Initializes the project calculation mapping by generating a dictionary that maps project types to their corresponding
        calculation classes.

        Raises:
            Exception: If a duplicate project type is found in the projects configuration.
        """
        if self._project_calculation_mapping != {}:
            return
        # Generate project function mapping
        self._project_calculation_mapping = dict()
        for project_config in projects_config:
            key = project_config.project_type
            if key in self._project_calculation_mapping:
                raise Exception('Duplicate project type found')
            module = importlib.import_module(project_config.processor.module)
            class_ = getattr(module, project_config.processor.class_name)
            self._project_calculation_mapping[key] = class_()

    async def _init_ipfs_client(self):
        """
        Initializes the IPFS client by creating a singleton instance of AsyncIPFSClientSingleton
        and initializing its sessions. The write and read clients are then assigned to instance variables.
        """
        self._ipfs_singleton = AsyncIPFSClientSingleton(settings.ipfs)
        await self._ipfs_singleton.init_sessions()
        self._ipfs_writer_client = self._ipfs_singleton._ipfs_write_client
        self._ipfs_reader_client = self._ipfs_singleton._ipfs_read_client

    async def init_worker(self):
        """
        Initializes the worker by initializing project calculation mapping, IPFS client, and other necessary components.
        """
        if not self._initialized:
            await self._init_project_calculation_mapping()
            await self._init_ipfs_client()
            await self.init()
