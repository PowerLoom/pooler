import asyncio
import importlib
from typing import Callable
from typing import List
from typing import Union
from uuid import uuid4

from aio_pika import IncomingMessage
from aio_pika import Message
from pydantic import ValidationError

from pooler.settings.config import projects_config
from pooler.settings.config import settings
from pooler.utils.callback_helpers import notify_on_task_failure_snapshot
from pooler.utils.data_utils import get_source_chain_id
from pooler.utils.generic_worker import GenericAsyncWorker
from pooler.utils.models.message_models import PayloadCommitMessage
from pooler.utils.models.message_models import PowerloomSnapshotProcessMessage
from pooler.utils.models.message_models import SnapshotBase
from pooler.utils.redis.rate_limiter import load_rate_limiter_scripts


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
        self._initialized = False

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

        try:
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
                epoch=msg_obj,
                cb_fn_async=stream_processor.compute,
                data_source_contract_address=msg_obj.contract,
                task_type=task_type,
                transformation_lambdas=stream_processor.transformation_lambdas,
            )

            await self._send_payload_commit_service_queue(
                audit_stream=task_type,
                epoch=msg_obj,
                snapshot=snapshot,
            )
        except Exception as e:
            del self._running_callback_tasks[self_unique_id]
            raise e

    async def _send_payload_commit_service_queue(
        self,
        audit_stream,
        epoch: PowerloomSnapshotProcessMessage,
        snapshot: Union[SnapshotBase, None],
    ):

        if not snapshot:
            self._logger.error(
                (
                    'No epoch snapshot to commit. Construction of snapshot'
                    ' failed for {} against epoch {}'
                ),
                audit_stream,
                epoch,
            )
        else:
            source_chain_details = await get_source_chain_id(
                redis_conn=self._redis_conn,
                rpc_helper=self._anchor_rpc_helper,
                state_contract_obj=self.protocol_state_contract,
            )

            payload = snapshot.dict()
            project_id = f'{audit_stream}:{epoch.contract}:{settings.namespace}'

            commit_payload = PayloadCommitMessage(
                message=payload,
                web3Storage=settings.web3storage.upload_snapshots,
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

            except Exception as e:
                self._logger.opt(exception=True).error(
                    (
                        'Exception committing snapshot to audit protocol:'
                        ' {} | dump: {}'
                    ),
                    snapshot,
                    e,
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

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        task_type = message.routing_key.split('.')[-1]
        if task_type not in self._task_types:
            return

        await message.ack()

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
        if not self._initialized:
            await self._init_redis_pool()
            await self._init_httpx_client()
            await self._init_rpc_helper()
            await self._init_project_calculation_mapping()
        self._initialized = True
