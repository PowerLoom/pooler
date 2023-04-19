import asyncio
import importlib
import json
import time
from typing import Callable
from typing import List
from typing import Union
from uuid import uuid4

from aio_pika import IncomingMessage
from pydantic import ValidationError

from pooler.settings.config import projects_config
from pooler.settings.config import settings
from pooler.utils.callback_helpers import AuditProtocolCommandsHelper
from pooler.utils.callback_helpers import notify_on_task_failure_snapshot
from pooler.utils.generic_worker import GenericAsyncWorker
from pooler.utils.models.data_models import PayloadCommitAPIRequest
from pooler.utils.models.message_models import PowerloomSnapshotProcessMessage
from pooler.utils.models.message_models import SnapshotBase
from pooler.utils.redis.rate_limiter import load_rate_limiter_scripts
from pooler.utils.redis.redis_keys import (
    cb_broadcast_processing_logs_zset,
)


class SnapshotAsyncWorker(GenericAsyncWorker):

    def __init__(self, name, **kwargs):
        super(SnapshotAsyncWorker, self).__init__(name=name, **kwargs)

        self._project_calculation_mapping = None
        self._task_types = []
        for project_config in projects_config:
            type_ = project_config.project_type
            self._task_types.append(type_)

    @notify_on_task_failure_snapshot
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

        stream_processor = self._project_calculation_mapping[task_type]
        snapshot = await self._map_processed_epochs_to_adapters(
            epoch=epoch,
            cb_fn_async=stream_processor.compute,
            data_source_contract_address=msg_obj.contract,
            task_type=task_type,
            transformation_lambdas=stream_processor.transformation_lambdas,
        )

        await self._send_audit_payload_commit_service(
            audit_stream=task_type,
            original_epoch=msg_obj,
            epoch_snapshot=snapshot,
        )

        del self._running_callback_tasks[self_unique_id]

    async def _send_audit_payload_commit_service(
        self,
        audit_stream,
        original_epoch: PowerloomSnapshotProcessMessage,
        epoch_snapshot: Union[SnapshotBase, None],
    ):

        if not epoch_snapshot:
            self._logger.error(
                (
                    'No epoch snapshot to commit. Construction of snapshot'
                    ' failed for {} against epoch {}'
                ),
                audit_stream,
                original_epoch,
            )
            # TODO: standardize/unify update log data model
            update_log = {
                'worker': self._unique_id,
                'update': {
                    'action': f'SnapshotBuild-{audit_stream}',
                    'info': {
                        'epoch': original_epoch.dict(),
                        'status': 'Failed',
                    },
                },
            }

            await self._redis_conn.zadd(
                name=cb_broadcast_processing_logs_zset.format(
                    original_epoch.broadcast_id,
                ),
                mapping={json.dumps(update_log): int(time.time())},
            )
        else:
            update_log = {
                'worker': self._unique_id,
                'update': {
                    'action': f'SnapshotBuild-{audit_stream}',
                    'info': {
                        'original_epoch': original_epoch.dict(),
                        'status': 'Success',
                        'snapshot': epoch_snapshot.dict(),
                    },
                },
            }

            await self._redis_conn.zadd(
                name=cb_broadcast_processing_logs_zset.format(
                    original_epoch.broadcast_id,
                ),
                mapping={json.dumps(update_log): int(time.time())},
            )
            source_chain_details = settings.chain_id

            payload = epoch_snapshot.dict()
            project_id = f'{audit_stream}_{original_epoch.contract}_{settings.namespace}'

            commit_payload = PayloadCommitAPIRequest(
                projectId=project_id,
                payload=payload,
                sourceChainDetails=source_chain_details,
            )

            try:
                r = await AuditProtocolCommandsHelper.commit_payload(
                    report_payload=commit_payload,
                    session=self._client,
                )
            except Exception as e:
                self._logger.opt(exception=True).error(
                    (
                        'Exception committing snapshot to audit protocol:'
                        ' {} | dump: {}'
                    ),
                    epoch_snapshot,
                    e,
                )
                update_log = {
                    'worker': self._unique_id,
                    'update': {
                        'action': f'SnapshotCommit-{audit_stream}',
                        'info': {
                            'snapshot': payload,
                            'original_epoch': original_epoch.dict(),
                            'status': 'Failed',
                            'exception': e,
                        },
                    },
                }

                await self._redis_conn.zadd(
                    name=cb_broadcast_processing_logs_zset.format(
                        original_epoch.broadcast_id,
                    ),
                    mapping={json.dumps(update_log): int(time.time())},
                )
            else:
                self._logger.debug(
                    (
                        'Sent snapshot to audit protocol payload commit'
                        ' service: {} | Response: {}, Time: {}'
                    ),
                    commit_payload,
                    r,
                    int(time.time()),
                )
                update_log = {
                    'worker': self._unique_id,
                    'update': {
                        'action': f'SnapshotCommit-{audit_stream}',
                        'info': {
                            'snapshot': payload,
                            'original_epoch': original_epoch.dict(),
                            'status': 'Success',
                            'response': r,
                        },
                    },
                }

                await self._redis_conn.zadd(
                    name=cb_broadcast_processing_logs_zset.format(
                        original_epoch.broadcast_id,
                    ),
                    mapping={json.dumps(update_log): int(time.time())},
                )

    async def _map_processed_epochs_to_adapters(
        self,
        epoch: PowerloomSnapshotProcessMessage,
        cb_fn_async,
        data_source_contract_address,
        task_type,
        transformation_lambdas: List[Callable],
    ):
        try:
            result = await cb_fn_async(
                min_chain_height=epoch.begin,
                max_chain_height=epoch.end,
                data_source_contract_address=data_source_contract_address,
                redis_conn=self._redis_conn,
                rpc_helper=self._rpc_helper,
            )

            if transformation_lambdas:
                for each_lambda in transformation_lambdas:
                    result = each_lambda(result, data_source_contract_address, epoch.begin, epoch.end)

            return result

        except Exception as e:
            self._logger.opt(exception=True).error(
                (
                    'Error while processing epoch {} for callback processor'
                    ' of type {}'
                ),
                epoch,
                task_type,
            )
            raise e

    async def _update_broadcast_processing_status(
        self, broadcast_id, update_state,
    ):
        await self._redis_conn.hset(
            cb_broadcast_processing_logs_zset.format(self.name),
            broadcast_id,
            json.dumps(update_state),
        )

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        task_type = message.routing_key.split('.')[-1]
        if task_type not in self._task_types:
            return

        await self.init()

        self._logger.debug('task type: {}', task_type)

        try:
            msg_obj: PowerloomSnapshotProcessMessage = (
                PowerloomSnapshotProcessMessage.parse_raw(message.body)
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

        asyncio.ensure_future(self._processor_task(msg_obj=msg_obj, task_type=task_type))
        await message.ack()

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

    async def init(self):
        await self._init_redis_pool()
        await self._init_httpx_client()
        await self._init_rpc_helper()
        await self._init_project_calculation_mapping()
