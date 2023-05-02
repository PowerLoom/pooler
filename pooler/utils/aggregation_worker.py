import asyncio
import importlib
import json
import time
from typing import Callable
from typing import List
from typing import Union
from uuid import uuid4

from aio_pika import IncomingMessage
from aio_pika import Message
from pydantic import ValidationError

from pooler.settings.config import aggregator_config
from pooler.settings.config import projects_config
from pooler.settings.config import settings
from pooler.utils.callback_helpers import notify_on_task_failure_aggregate
from pooler.utils.generic_worker import GenericAsyncWorker
from pooler.utils.models.message_models import AggregateBase
from pooler.utils.models.message_models import PayloadCommitMessage
from pooler.utils.models.message_models import PowerloomCalculateAggregateMessage
from pooler.utils.models.message_models import PowerloomSnapshotFinalizedMessage
from pooler.utils.models.settings_model import AggregateOn
from pooler.utils.redis.rate_limiter import load_rate_limiter_scripts
from pooler.utils.redis.redis_keys import (
    cb_broadcast_processing_logs_zset,
)


class AggregationAsyncWorker(GenericAsyncWorker):

    def __init__(self, name, **kwargs):
        self._q = f'powerloom-backend-cb-aggregate:{settings.namespace}:{settings.instance_id}'
        self._rmq_routing = f'powerloom-backend-callback:{settings.namespace}'
        f':{settings.instance_id}:CalculateAggregate.*'
        super(AggregationAsyncWorker, self).__init__(name=name, **kwargs)

        self._project_calculation_mapping = None
        self._initialized = False
        self._single_project_types = set()
        self._multi_project_types = set()
        self._task_types = set()

        for config in aggregator_config:
            if config.aggregate_on == AggregateOn.single_project:
                self._single_project_types.add(config.project_type)
            elif config.aggregate_on == AggregateOn.multi_project:
                self._multi_project_types.add(config.project_type)
            self._task_types.add(config.project_type)

    @notify_on_task_failure_aggregate
    async def _processor_task(
        self,
        msg_obj: Union[PowerloomSnapshotFinalizedMessage, PowerloomCalculateAggregateMessage],
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

        self_unique_id = str(uuid4())
        cur_task: asyncio.Task = asyncio.current_task(
            asyncio.get_running_loop(),
        )
        cur_task.set_name(
            f'aio_pika.consumer|Processor|{task_type}|{msg_obj.broadcastId}',
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
            msg_obj=msg_obj,
            cb_fn_async=stream_processor.compute,
            task_type=task_type,
            transformation_lambdas=stream_processor.transformation_lambdas,
        )

        await self._send_audit_payload_commit_service(
            audit_stream=task_type,
            epoch=msg_obj,
            snapshot=snapshot,
        )

        del self._running_callback_tasks[self_unique_id]

    def _gen_single_type_project_id(self, type_, epoch):
        contract = epoch.projectId.split('_')[-2]
        project_id = project_id = f'{type_}_{contract}_{settings.namespace}'
        return project_id

    def _gen_multiple_type_project_id(self, type_, epoch):
        project_hash = hash([project.projectId for project in epoch.messages])
        project_id = f'{type_}_{project_hash}_{settings.namespace}'

    def _gen_project_id(self, type_, epoch):
        if type_ in self._single_project_types:
            return self._gen_single_type_project_id(type_, epoch)
        elif type_ in self._multi_project_types:
            return self._gen_multiple_type_project_id(type_, epoch)
        else:
            raise ValueError(f'Unknown project type {type_}')

    async def _send_audit_payload_commit_service(
        self,
        audit_stream,
        epoch: Union[PowerloomSnapshotFinalizedMessage, PowerloomCalculateAggregateMessage],
        snapshot: Union[AggregateBase, None],
    ):

        if not snapshot:
            self._logger.error(
                (
                    'No aggreagate snapshot to commit. Construction of snapshot'
                    ' failed for {} against epoch {}'
                ),
                audit_stream,
                epoch,
            )
            # TODO: standardize/unify update log data model
            update_log = {
                'worker': self._unique_id,
                'update': {
                    'action': f'AggregateBuild-{audit_stream}',
                    'info': {
                        'epoch': epoch.dict(),
                        'status': 'Failed',
                    },
                },
            }

            await self._redis_conn.zadd(
                name=cb_broadcast_processing_logs_zset.format(
                    epoch.broadcastId,
                ),
                mapping={json.dumps(update_log): int(time.time())},
            )
        else:
            update_log = {
                'worker': self._unique_id,
                'update': {
                    'action': f'AggregateBuild-{audit_stream}',
                    'info': {
                        'epoch': epoch.dict(),
                        'status': 'Success',
                        'snapshot': snapshot.dict(),
                    },
                },
            }

            await self._redis_conn.zadd(
                name=cb_broadcast_processing_logs_zset.format(
                    epoch.broadcastId,
                ),
                mapping={json.dumps(update_log): int(time.time())},
            )
            source_chain_details = settings.chain_id

            payload = snapshot.dict()

            project_id = self._gen_project_id(audit_stream, epoch)

            commit_payload = PayloadCommitMessage(
                message=payload,
                web3Storage=True,
                sourceChainId=source_chain_details,
                projectId=project_id,
                epochId=epoch.epochId,
            )

            exchange = (
                f'{settings.rabbitmq.setup.commit_payload.exchange}:{settings.namespace}'
            )
            routing_key = f'powerloom-backend-commit-payload:{settings.namespace}:{settings.instance_id}.Data'

            # send through rabbitmq
            try:
                async with self._rmq_connection_pool.acquire() as connection:
                    async with self._rmq_channel_pool.acquire() as channel:
                        # Prepare a message to send

                        commit_payload_exchange = await channel.get_exchange(
                            name=exchange,
                        )
                        message_data = commit_payload.json().encode()

                        # Prepare a message to send
                        message = Message(message_data)

                        await commit_payload_exchange.publish(
                            message=message,
                            routing_key=routing_key,
                        )

                        self._logger.info(
                            'Sent message to commit payload queue: {}', commit_payload,
                        )

                        update_log = {
                            'worker': self._unique_id,
                            'update': {
                                'action': f'AggregateCommit-{audit_stream}',
                                'info': {
                                    'snapshot': payload,
                                    'epoch': epoch.dict(),
                                    'status': 'Success',
                                },
                            },
                        }

                        await self._redis_conn.zadd(
                            name=cb_broadcast_processing_logs_zset.format(
                                epoch.broadcastId,
                            ),
                            mapping={json.dumps(update_log): int(time.time())},
                        )

            except Exception as e:
                self._logger.opt(exception=True).error(
                    (
                        'Exception committing snapshot to audit protocol:'
                        ' {} | dump: {}'
                    ),
                    snapshot,
                    e,
                )
                update_log = {
                    'worker': self._unique_id,
                    'update': {
                        'action': f'AggregateCommit-{audit_stream}',
                        'info': {
                            'snapshot': payload,
                            'epoch': epoch.dict(),
                            'status': 'Failed',
                            'exception': e,
                        },
                    },
                }

                await self._redis_conn.zadd(
                    name=cb_broadcast_processing_logs_zset.format(
                        epoch.broadcastId,
                    ),
                    mapping={json.dumps(update_log): int(time.time())},
                )

    async def _map_processed_epochs_to_adapters(
        self,
        msg_obj: Union[PowerloomSnapshotFinalizedMessage, PowerloomCalculateAggregateMessage],
        cb_fn_async,
        task_type,
        transformation_lambdas: List[Callable],
    ):

        try:

            project_id = self._gen_project_id(task_type, msg_obj)

            result = await cb_fn_async(
                msg_obj=msg_obj,
                redis=self._redis_conn,
                rpc_helper=self._rpc_helper,
                anchor_rpc_helper=self._anchor_rpc_helper,
                protocol_state_contract=self.protocol_state_contract,
                project_id=project_id,
            )

            if transformation_lambdas:
                for each_lambda in transformation_lambdas:
                    result = each_lambda(result, msg_obj)

            return result

        except Exception as e:
            self._logger.opt(exception=True).error(
                (
                    'Error while processing aggregate {} for callback processor'
                    ' of type {}'
                ),
                msg_obj,
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
        # TODO: Update based on new single project based design
        if task_type in self._single_project_types:
            try:
                msg_obj: PowerloomSnapshotFinalizedMessage = (
                    PowerloomSnapshotFinalizedMessage.parse_raw(message.body)
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
        await message.ack()

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

    async def init(self):
        if not self._initialized:
            await self._init_redis_pool()
            await self._init_httpx_client()
            await self._init_rpc_helper()
            await self._init_project_calculation_mapping()
        self._initialized = True
