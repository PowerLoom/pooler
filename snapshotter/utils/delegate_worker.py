import asyncio
import importlib
import json
import time

from aio_pika import IncomingMessage
from aio_pika import Message
from pydantic import BaseModel
from pydantic import ValidationError

from snapshotter.init_rabbitmq import get_delegate_worker_request_queue_routing_key
from snapshotter.init_rabbitmq import get_delegate_worker_response_queue_routing_key_pattern
from snapshotter.settings.config import delegate_tasks
from snapshotter.settings.config import settings
from snapshotter.utils.callback_helpers import send_failure_notifications_async
from snapshotter.utils.generic_worker import GenericAsyncWorker
from snapshotter.utils.models.data_models import DelegateTaskProcessorIssue
from snapshotter.utils.models.message_models import PowerloomDelegateWorkerRequestMessage
from snapshotter.utils.redis.rate_limiter import load_rate_limiter_scripts


class DelegateAsyncWorker(GenericAsyncWorker):
    def __init__(self, name, **kwargs):
        """
        Initializes a new instance of the DelegateAsyncWorker class.

        Args:
            name (str): The name of the worker.
            **kwargs: Additional keyword arguments to pass to the base class constructor.
        """
        super(DelegateAsyncWorker, self).__init__(name=name, **kwargs)
        self._qos = 1
        self._exchange_name = f'{settings.rabbitmq.setup.delegated_worker.exchange}:Request:{settings.namespace}'
        self._response_exchange_name = f'{settings.rabbitmq.setup.delegated_worker.exchange}:Response:{settings.namespace}'
        self._delegate_task_calculation_mapping = None
        self._task_types = []
        for task in delegate_tasks:
            task_type = task.task_type
            self._task_types.append(task_type)

        self._q, self._rmq_routing = get_delegate_worker_request_queue_routing_key()

    async def _processor_task(self, msg_obj: PowerloomDelegateWorkerRequestMessage):
        """
        Process a delegate task for the given message object.

        Args:
            msg_obj (PowerloomDelegateWorkerRequestMessage): The message object containing the task to process.

        Returns:
            None
        """
        self._logger.trace(
            'Processing delegate task for {}', msg_obj,
        )

        if msg_obj.task_type not in self._delegate_task_calculation_mapping:
            self._logger.error(
                (
                    'No delegate task calculation mapping found for task type'
                    f' {msg_obj.task_type}. Skipping... {self._delegate_task_calculation_mapping}'
                ),
            )
            return

        try:
            if not self._rate_limiting_lua_scripts:
                self._rate_limiting_lua_scripts = await load_rate_limiter_scripts(
                    self._redis_conn,
                )

            task_processor = self._delegate_task_calculation_mapping[msg_obj.task_type]

            result = await task_processor.compute(
                msg_obj=msg_obj,
                redis_conn=self._redis_conn,
                rpc_helper=self._rpc_helper,
            )

            self._logger.trace('got result from delegate worker compute {}', result)
            await self._send_delegate_worker_response_queue(
                request_msg=msg_obj,
                response_msg=result,
            )
        except Exception as e:
            self._logger.opt(exception=settings.logs.trace_enabled).error(
                'Exception while processing tx receipt fetch for {}: {}', msg_obj, e,
            )

            notification_message = DelegateTaskProcessorIssue(
                instanceID=settings.instance_id,
                issueType='DELEGATE_TASK_FAILURE',
                epochId=msg_obj.epochId,
                timeOfReporting=time.time(),
                exception=json.dumps({'issueDetails': f'Error : {e}'}),
            )
            # send failure notifications
            await send_failure_notifications_async(
                client=self._client,
                message=notification_message,
            )
        finally:
            await self._redis_conn.close()

    # TODO: send to delegate worker response queue
    async def _send_delegate_worker_response_queue(
        self,
        request_msg: PowerloomDelegateWorkerRequestMessage,
        response_msg: BaseModel,
    ):
        """
        Sends a response message to the delegate worker response queue.

        Args:
            request_msg (PowerloomDelegateWorkerRequestMessage): The request message that triggered the response.
            response_msg (BaseModel): The response message to send.

        Raises:
            Exception: If there was an error sending the message to the delegate worker response queue.
        """
        response_queue_name, response_routing_key_pattern = get_delegate_worker_response_queue_routing_key_pattern()

        response_routing_key = response_routing_key_pattern.replace(
            '*', request_msg.extra['unique_id'],
        )

        # send through rabbitmq
        try:
            async with self._rmq_channel_pool.acquire() as channel:
                # Prepare a message to send
                delegate_workers_response_exchange = await channel.get_exchange(
                    # request and response payloads for delegate workers are sent through the same exchange
                    name=self._response_exchange_name,
                )
                message_data = response_msg.json().encode('utf-8')
                # Prepare a message to send
                message = Message(message_data)
                await delegate_workers_response_exchange.publish(
                    message=message,
                    routing_key=response_routing_key,
                )

        except Exception as e:
            self._logger.opt(exception=settings.logs.trace_enabled).error(
                (
                    'Exception sending message to delegate :'
                    ' {} | dump: {}'
                ),
                response_msg,
                e,
            )

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        """
        Callback function that is called when a message is received from RabbitMQ.
        It processes the message and starts a new task to handle the message.

        Args:
            message (IncomingMessage): The incoming message from RabbitMQ.

        Returns:
            None
        """
        if not self._initialized:
            await self.init_worker()

        try:
            msg_obj: PowerloomDelegateWorkerRequestMessage = (
                PowerloomDelegateWorkerRequestMessage.parse_raw(message.body)
            )
            task_type = msg_obj.task_type
            if task_type not in self._task_types:
                self._logger.error(task_type, self._task_types)
                return
            await message.ack()

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
        asyncio.ensure_future(self._processor_task(msg_obj=msg_obj))

    async def init_worker(self):
        """
        Initializes the worker by calling the _init_delegate_task_calculation_mapping and init functions.
        """
        if not self._initialized:
            await self._init_delegate_task_calculation_mapping()
            await self.init()

    async def _init_delegate_task_calculation_mapping(self):
        """
        Initializes the mapping of delegate tasks to their corresponding calculation classes.
        """
        if self._delegate_task_calculation_mapping is not None:
            return
        # Generate project function mapping
        self._delegate_task_calculation_mapping = dict()
        for delegate_task in delegate_tasks:
            key = delegate_task.task_type

            module = importlib.import_module(delegate_task.module)
            class_ = getattr(module, delegate_task.class_name)
            self._delegate_task_calculation_mapping[key] = class_()
