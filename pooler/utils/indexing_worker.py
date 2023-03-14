import asyncio
import json
from uuid import uuid4

from aio_pika import IncomingMessage
from pydantic import ValidationError

from pooler.utils.generic_worker import GenericAsyncWorker
from pooler.utils.redis.rate_limiter import load_rate_limiter_scripts
from pooler.utils.redis.redis_keys import (
    cb_broadcast_processing_logs_zset,
)


class IndexingAsyncWorker(GenericAsyncWorker):

    def __init__(self, name, **kwargs):
        super(IndexingAsyncWorker, self).__init__(name=name, **kwargs)

        self._index_calculation_mapping = None
        self._task_types = []
        # TODO: Fill task_types from indexing config

    # TODO: Add interfaces and notifiers for indexing failure
    # @notify_on_task_failure
    # TODO: Write msg_obj interface and fill it in function definition
    async def _processor_task(self, msg_obj, task_type: str):
        """Function used to process the received message object."""
        self._logger.debug(
            'Processing callback: {}', msg_obj,
        )

        await self.init()

        if task_type not in self._index_calculation_mapping:
            self._logger.error(
                (
                    'No index calculation mapping found for task type'
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

        # TODO: Add indexing calculation and submission logic here

        del self._running_callback_tasks[self_unique_id]

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

        self._logger.debug('task type: {}', task_type)
        await message.ack()

        try:
            # TODO: parse message here and load it in msg_obj (replace the line below)
            msg_obj = message.body
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

    async def _init_index_calculation_mapping(self):
        if self._project_calculation_mapping is not None:
            return
        # Generate index function mapping
        self._index_calculation_mapping = dict()

        # TODO: Fill index calculation mapping from indexing config

        # SAMPLE CODE FOR LOADING PROJECT CONFIG
        # for project_config in projects_config:
        #     key = project_config.project_type
        #     if key in self._project_calculation_mapping:
        #         raise Exception('Duplicate project type found')
        #     module = importlib.import_module(project_config.processor.module)
        #     class_ = getattr(module, project_config.processor.class_name)
        #     self._project_calculation_mapping[key] = class_()

    async def init(self):
        await self._init_redis_pool()
        await self._init_httpx_client()
        await self._init_rpc_helper()
        await self._init_project_calculation_mapping()
