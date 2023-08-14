import asyncio
import hashlib
import importlib
import json
import time
from typing import Union

from aio_pika import IncomingMessage
from ipfs_client.main import AsyncIPFSClient
from ipfs_client.main import AsyncIPFSClientSingleton
from pydantic import ValidationError

from snapshotter.settings.config import aggregator_config
from snapshotter.settings.config import projects_config
from snapshotter.settings.config import settings
from snapshotter.utils.callback_helpers import send_failure_notifications_async
from snapshotter.utils.generic_worker import GenericAsyncWorker
from snapshotter.utils.models.data_models import SnapshotterIssue, SnapshotterReportState
from snapshotter.utils.models.message_models import PowerloomCalculateAggregateMessage
from snapshotter.utils.models.message_models import PowerloomSnapshotSubmittedMessage
from snapshotter.utils.models.settings_model import AggregateOn
from snapshotter.utils.redis.rate_limiter import load_rate_limiter_scripts


class AggregationAsyncWorker(GenericAsyncWorker):
    _ipfs_singleton: AsyncIPFSClientSingleton
    _ipfs_writer_client: AsyncIPFSClient
    _ipfs_reader_client: AsyncIPFSClient

    def __init__(self, name, **kwargs):
        self._q = f'powerloom-backend-cb-aggregate:{settings.namespace}:{settings.instance_id}'
        self._rmq_routing = f'powerloom-backend-callback:{settings.namespace}'
        f':{settings.instance_id}:CalculateAggregate.*'
        super(AggregationAsyncWorker, self).__init__(name=name, **kwargs)

        self._project_calculation_mapping = None
        self._single_project_types = set()
        self._multi_project_types = set()
        self._task_types = set()
        self._ipfs_singleton = None

        for config in aggregator_config:
            if config.aggregate_on == AggregateOn.single_project:
                self._single_project_types.add(config.project_type)
            elif config.aggregate_on == AggregateOn.multi_project:
                self._multi_project_types.add(config.project_type)
            self._task_types.add(config.project_type)

    def _gen_single_type_project_id(self, type_, epoch):
        data_source = epoch.projectId.split(':')[-2]
        project_id = f'{type_}:{data_source}:{settings.namespace}'
        return project_id

    def _gen_multiple_type_project_id(self, type_, epoch):

        underlying_project_ids = [project.projectId for project in epoch.messages]
        unique_project_id = ''.join(sorted(underlying_project_ids))

        project_hash = hashlib.sha3_256(unique_project_id.encode()).hexdigest()

        project_id = f'{type_}:{project_hash}:{settings.namespace}'
        return project_id

    def _gen_project_id(self, type_, epoch):
        if type_ in self._single_project_types:
            return self._gen_single_type_project_id(type_, epoch)
        elif type_ in self._multi_project_types:
            return self._gen_multiple_type_project_id(type_, epoch)
        else:
            raise ValueError(f'Unknown project type {type_}')

    async def _processor_task(
        self,
        msg_obj: Union[PowerloomSnapshotSubmittedMessage, PowerloomCalculateAggregateMessage],
        task_type: str,
    ):
        """Function used to process the received message object."""
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

        project_id = self._gen_project_id(task_type, msg_obj)

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

            snapshot = await task_processor.compute(
                msg_obj=msg_obj,
                redis=self._redis_conn,
                rpc_helper=self._rpc_helper,
                anchor_rpc_helper=self._anchor_rpc_helper,
                ipfs_reader=self._ipfs_reader_client,
                protocol_state_contract=self.protocol_state_contract,
                project_id=project_id,
            )

            if task_processor.transformation_lambdas:
                for each_lambda in task_processor.transformation_lambdas:
                    snapshot = each_lambda(snapshot, msg_obj)

            await self._send_payload_commit_service_queue(
                type_=task_type,
                project_id=project_id,
                epoch=msg_obj,
                snapshot=snapshot,
                storage_flag=settings.web3storage.upload_aggregates,
            )
        except Exception as e:
            self._logger.opt(exception=True).error(
                'Exception processing callback for epoch: {}, Error: {},'
                'sending failure notifications', msg_obj, e,
            )
            notification_message = SnapshotterIssue(
                instanceID=settings.instance_id,
                issueType=SnapshotterReportState.MISSED_SNAPSHOT.value,
                projectID=project_id,
                epochId=str(msg_obj.epochId),
                timeOfReporting=str(time.time()),
                extra=json.dumps({'issueDetails': f'Error : {e}'}),
            )
            await send_failure_notifications_async(
                client=self._client, message=notification_message,
            )
        finally:
            await self._redis_conn.close()

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        task_type = message.routing_key.split('.')[-1]
        if task_type not in self._task_types:
            return

        await message.ack()

        await self.init_worker()

        self._logger.debug('task type: {}', task_type)
        # TODO: Update based on new single project based design
        if task_type in self._single_project_types:
            try:
                msg_obj: PowerloomSnapshotSubmittedMessage = (
                    PowerloomSnapshotSubmittedMessage.parse_raw(message.body)
                )
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
        elif task_type in self._multi_project_types:
            try:
                msg_obj: PowerloomCalculateAggregateMessage = (
                    PowerloomCalculateAggregateMessage.parse_raw(message.body)
                )
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
        else:
            self._logger.error(
                'Unknown task type {}', task_type,
            )
            return
        asyncio.ensure_future(self._processor_task(msg_obj=msg_obj, task_type=task_type))

    async def _init_project_calculation_mapping(self):
        if self._project_calculation_mapping is not None:
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
        if not self._ipfs_singleton:
            self._ipfs_singleton = AsyncIPFSClientSingleton(settings.ipfs)
            await self._ipfs_singleton.init_sessions()
            self._ipfs_writer_client = self._ipfs_singleton._ipfs_write_client
            self._ipfs_reader_client = self._ipfs_singleton._ipfs_read_client

    async def init_worker(self):
        if not self._initialized:
            await self._init_project_calculation_mapping()
            await self._init_ipfs_client()
            await self.init()
