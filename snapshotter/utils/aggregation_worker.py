import asyncio
import hashlib
import importlib
import json
import time
from typing import Union

from aio_pika import IncomingMessage
from aio_pika import Message
from ipfs_client.main import AsyncIPFSClient
from ipfs_client.main import AsyncIPFSClientSingleton
from pydantic import ValidationError

from snapshotter.settings.config import aggregator_config
from snapshotter.settings.config import projects_config
from snapshotter.settings.config import settings
from snapshotter.utils import event_log_decoder
from snapshotter.utils.callback_helpers import send_failure_notifications_async
from snapshotter.utils.generic_worker import GenericAsyncWorker
from snapshotter.utils.models.data_models import SnapshotterIssue
from snapshotter.utils.models.data_models import SnapshotterReportState
from snapshotter.utils.models.data_models import SnapshotterStates
from snapshotter.utils.models.data_models import SnapshotterStateUpdate
from snapshotter.utils.models.message_models import CalculateAggregateMessage
from snapshotter.utils.models.message_models import ProjectTypeProcessingCompleteMessage
from snapshotter.utils.models.message_models import SnapshotSubmittedMessageLite
from snapshotter.utils.models.settings_model import AggregateOn
from snapshotter.utils.redis.rate_limiter import load_rate_limiter_scripts
from snapshotter.utils.redis.redis_keys import epoch_id_project_to_state_mapping


class AggregationAsyncWorker(GenericAsyncWorker):
    _ipfs_singleton: AsyncIPFSClientSingleton
    _ipfs_writer_client: AsyncIPFSClient
    _ipfs_reader_client: AsyncIPFSClient

    def __init__(self, name, **kwargs):
        """
        Initializes an instance of AggregationAsyncWorker.

        Args:
            name (str): The name of the worker.
            **kwargs: Additional keyword arguments to be passed to the parent class constructor.
        """
        self._q = f'backend-cb-aggregate:{settings.namespace}:{settings.instance_id}'
        self._rmq_routing = f'backend-callback:{settings.namespace}'
        f':{settings.instance_id}:CalculateAggregate.*'
        super(AggregationAsyncWorker, self).__init__(name=name, **kwargs)

        self._project_calculation_mapping = dict()
        self._single_project_types = set()
        self._multi_project_types = set()
        self._task_types = set()

        for config in aggregator_config:
            if config.aggregate_on == AggregateOn.single_project:
                self._single_project_types.add(config.project_type)
            elif config.aggregate_on == AggregateOn.multi_project:
                self._multi_project_types.add(config.project_type)
            self._task_types.add(config.project_type)

    def _gen_single_type_project_id(self, task_type, msg_obj):
        """
        Generates a project ID for a single task type and epoch.

        Args:
            task_type (str): The task type.
            epoch (Epoch): The epoch object.

        Returns:
            str: The generated project ID.
        """
        data_source = msg_obj.projectId.split(':')[-2]
        project_id = f'{task_type}:{data_source}:{settings.namespace}'
        return project_id

    def _gen_project_id(self, task_type, msg_obj):
        """
        Generates a project ID based on the given task type and epoch.

        Args:
            task_type (str): The type of task.
            epoch (int): The epoch number.

        Returns:
            str: The generated project ID.

        Raises:
            ValueError: If the task type is unknown.
        """
        if task_type in self._single_project_types:
            return self._gen_single_type_project_id(task_type, msg_obj)
        elif task_type in self._multi_project_types:
            return f'{task_type}:{settings.namespace}'
        else:
            raise ValueError(f'Unknown project type {task_type}')

    async def _processor_task(
        self,
        msg_obj: Union[ProjectTypeProcessingCompleteMessage, CalculateAggregateMessage],
        task_type: str,
    ):
        """
        Process the given message object and task type.

        Args:
            msg_obj (Union[ProjectTypeProcessingCompleteMessage, CalculateAggregateMessage]):
                The message object to be processed.
            task_type (str): The type of task to be performed.

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

        if type(msg_obj) == ProjectTypeProcessingCompleteMessage:
            project_ids = []
            for submitted_snapshot in msg_obj.snapshotsSubmitted:
                project_ids.append(self._gen_project_id(task_type, submitted_snapshot))
        else:
            project_ids = [self._gen_project_id(task_type, msg_obj)]

        try:
            if not self._rate_limiting_lua_scripts:
                self._rate_limiting_lua_scripts = await load_rate_limiter_scripts(
                    self._redis_conn,
                )
            self._logger.debug(
                'Got epoch to process for {}: {}',
                task_type, msg_obj,
            )

            task_processor = self._project_calculation_mapping[task_type]

            snapshots = await task_processor.compute(
                msg_obj=msg_obj,
                redis=self._redis_conn,
                rpc_helper=self._rpc_helper,
                anchor_rpc_helper=self._anchor_rpc_helper,
                ipfs_reader=self._ipfs_reader_client,
                protocol_state_contract=self._protocol_state_contract,
                project_ids=project_ids,
            )

        except Exception as e:
            self._logger.opt(exception=settings.logs.trace_enabled).error(
                'Exception processing callback for epoch: {}, Task Type: {}, Error: {},'
                'sending failure notifications', msg_obj, task_type, e,
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
            submitted_snapshots = []
            if not snapshots:
                await self._redis_conn.hset(
                    name=epoch_id_project_to_state_mapping(
                        epoch_id=msg_obj.epochId, state_id=SnapshotterStates.SNAPSHOT_BUILD.value,
                    ),
                    mapping={
                        f'{task_type}:{settings.namespace}': SnapshotterStateUpdate(
                            status='failed', timestamp=int(time.time()), error='Empty snapshot',
                        ).json(),
                    },
                )
                notification_message = SnapshotterIssue(
                    instanceID=settings.instance_id,
                    issueType=SnapshotterReportState.MISSED_SNAPSHOT.value,
                    projectID=f'{task_type}:{settings.namespace}',
                    epochId=str(msg_obj.epochId),
                    timeOfReporting=str(time.time()),
                    extra=json.dumps({'issueDetails': 'Error : Empty snapshot'}),
                )
                await send_failure_notifications_async(
                    client=self._client, message=notification_message,
                )
            else:
                for project_id, snapshot in snapshots:
                    await self._redis_conn.hset(
                        name=epoch_id_project_to_state_mapping(
                            epoch_id=msg_obj.epochId, state_id=SnapshotterStates.SNAPSHOT_BUILD.value,
                        ),
                        mapping={
                            project_id: SnapshotterStateUpdate(
                                status='success', timestamp=int(time.time()),
                            ).json(),
                        },
                    )
                    snapshot_cid = await self._commit_payload(
                        task_type=task_type,
                        project_id=project_id,
                        epoch=msg_obj,
                        snapshot=snapshot,
                        storage_flag=settings.web3storage.upload_aggregates,
                        _ipfs_writer_client=self._ipfs_writer_client,
                    )

                    submitted_snapshots.append(
                        (project_id, snapshot_cid),
                    )

            self._logger.debug(
                'Updated epoch processing status in aggregation worker for project type {} for transition {}',
                task_type, SnapshotterStates.SNAPSHOT_BUILD.value,
            )

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

        await self._redis_conn.close()

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        """
        Callback function to handle incoming RabbitMQ messages.

        Args:
            message (IncomingMessage): The incoming RabbitMQ message.

        Returns:
            None
        """
        task_type = message.routing_key.split('.')[-1]
        if task_type not in self._task_types:
            return

        await message.ack()

        await self.init_worker()

        self._logger.debug('task type: {}', task_type)
        if task_type in self._single_project_types:
            try:
                msg_obj: ProjectTypeProcessingCompleteMessage = ProjectTypeProcessingCompleteMessage.parse_raw(
                    message.body,
                )
            except ValidationError as e:
                self._logger.opt(exception=settings.logs.trace_enabled).error(
                    (
                        'Bad message structure of callback processor. Error: {}'
                    ),
                    e,
                )
                return
            except Exception as e:
                self._logger.opt(exception=settings.logs.trace_enabled).error(
                    (
                        'Unexpected message structure of callback in processor. Error: {}'
                    ),
                    e,
                )
                return
        elif task_type in self._multi_project_types:
            try:
                msg_obj: CalculateAggregateMessage = (
                    CalculateAggregateMessage.parse_raw(message.body)
                )
            except ValidationError as e:
                self._logger.opt(exception=settings.logs.trace_enabled).error(
                    (
                        'Bad message structure of callback processor. Error: {}'
                    ),
                    e,
                )
                return
            except Exception as e:
                self._logger.opt(exception=settings.logs.trace_enabled).error(
                    (
                        'Unexpected message structure of callback in processor. Error: {}'
                    ),
                    e,
                )
                return
        else:
            self._logger.error(
                'Unknown task type {}', task_type,
            )
            return
        asyncio.ensure_future(self._processor_task(msg_obj=msg_obj, task_type=task_type))

    async def _init_project_calculation_mapping(self):
        """
        Initializes the project calculation mapping by importing the processor module and class for each project type
        specified in the aggregator and projects configuration. Raises an exception if a duplicate project type is found.
        """
        if self._project_calculation_mapping != {}:
            return

        self._project_calculation_mapping = dict()
        for project_config in aggregator_config:
            key = project_config.project_type
            if key in self._project_calculation_mapping:
                raise Exception('Duplicate project type found')
            module = importlib.import_module(project_config.processor.module)
            class_ = getattr(module, project_config.processor.class_name)
            self._project_calculation_mapping[key] = class_()
        for project_config in projects_config:
            key = project_config.project_type
            if key in self._project_calculation_mapping:
                raise Exception('Duplicate project type found')
            module = importlib.import_module(project_config.processor.module)
            class_ = getattr(module, project_config.processor.class_name)
            self._project_calculation_mapping[key] = class_()

    async def _init_ipfs_client(self):
        """
        Initializes the IPFS client and sets the write and read clients for the class.
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
