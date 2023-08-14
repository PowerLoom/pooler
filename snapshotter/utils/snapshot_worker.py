import asyncio
import importlib
import json
import time

from aio_pika import IncomingMessage
from pydantic import ValidationError

from snapshotter.settings.config import projects_config
from snapshotter.settings.config import settings
from snapshotter.utils.callback_helpers import send_failure_notifications_async
from snapshotter.utils.generic_worker import GenericAsyncWorker
from snapshotter.utils.models.data_models import SnapshotterIssue, SnapshotterReportState, SnapshotterStateUpdate, SnapshotterStates
from snapshotter.utils.models.message_models import PowerloomSnapshotProcessMessage
from snapshotter.utils.redis.rate_limiter import load_rate_limiter_scripts
from snapshotter.utils.redis.redis_keys import epoch_id_project_to_state_mapping


class SnapshotAsyncWorker(GenericAsyncWorker):
    def __init__(self, name, **kwargs):
        self._q = f'powerloom-backend-cb-snapshot:{settings.namespace}:{settings.instance_id}'
        self._rmq_routing = f'powerloom-backend-callback:{settings.namespace}:{settings.instance_id}:EpochReleased.*'
        super(SnapshotAsyncWorker, self).__init__(name=name, **kwargs)
        self._project_calculation_mapping = None
        self._task_types = []
        for project_config in projects_config:
            type_ = project_config.project_type
            self._task_types.append(type_)

    def _gen_project_id(self, type_: str, epoch):
        if not epoch.data_source:
            # For generic use cases that don't have a data source like block details
            project_id = f'{type_}:{settings.namespace}'
        else:
            if epoch.primary_data_source:
                project_id = f'{type_}:{epoch.primary_data_source}_{epoch.data_source}:{settings.namespace}'
            else:
                project_id = f'{type_}:{epoch.data_source}:{settings.namespace}'
        return project_id

    async def _processor_task(self, msg_obj: PowerloomSnapshotProcessMessage, task_type: str):
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

        project_id = self._gen_project_id(type_=task_type, epoch=msg_obj)

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
                epoch=msg_obj,
                redis_conn=self._redis_conn,
                rpc_helper=self._rpc_helper,
            )

            if task_processor.transformation_lambdas:
                for each_lambda in task_processor.transformation_lambdas:
                    snapshot = each_lambda(snapshot, msg_obj.data_source, msg_obj.begin, msg_obj.end)

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
            await self._redis_conn.hset(
                name=epoch_id_project_to_state_mapping(epoch_id=msg_obj.epochId, state_id=SnapshotterStates.SNAPSHOT_BUILD.value),
                mapping={
                    project_id: SnapshotterStateUpdate(
                        status='failed', error=str(e), timestamp=int(time.time())
                    ).json()
                },
            )
        else:
            await self._redis_conn.hset(
                name=epoch_id_project_to_state_mapping(epoch_id=msg_obj.epochId, state_id=SnapshotterStates.SNAPSHOT_BUILD.value),
                mapping={
                    project_id: SnapshotterStateUpdate(
                        status='success', timestamp=int(time.time())
                    ).json()
                },
            )
            await self._send_payload_commit_service_queue(
                type_=task_type,
                project_id=project_id,
                epoch=msg_obj,
                snapshot=snapshot,
                storage_flag=settings.web3storage.upload_snapshots,
            )
        await self._redis_conn.close()

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        task_type = message.routing_key.split('.')[-1]
        if task_type not in self._task_types:
            return

        await message.ack()

        await self.init_worker()

        self._logger.debug('task type: {}', task_type)

        try:
            msg_obj: PowerloomSnapshotProcessMessage = (
                PowerloomSnapshotProcessMessage.parse_raw(message.body)
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
        if self._project_calculation_mapping is not None:
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

    async def init_worker(self):
        if not self._initialized:
            await self._init_project_calculation_mapping()
            await self.init()
