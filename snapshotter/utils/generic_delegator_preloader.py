import asyncio
import uuid
from collections import defaultdict
from typing import Any
from typing import Dict

import aio_pika
import aiorwlock
from aio_pika import Message
from redis import asyncio as aioredis
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential

from snapshotter.init_rabbitmq import get_delegate_worker_request_queue_routing_key
from snapshotter.init_rabbitmq import get_delegate_worker_response_queue_routing_key_pattern
from snapshotter.settings.config import preloader_config
from snapshotter.settings.config import settings
from snapshotter.utils.callback_helpers import GenericDelegatorPreloader
from snapshotter.utils.callback_helpers import get_rabbitmq_basic_connection_async
from snapshotter.utils.models.message_models import EpochBase
from snapshotter.utils.rpc import RpcHelper


class DelegatorPreloaderAsyncWorker(GenericDelegatorPreloader):
    def __init__(self, **kwargs):
        """
        Initializes the delegator preloader.
        Args:
            **kwargs: Arbitrary keyword arguments.

        Attributes:
            _qos (int): Quality of service.
            _filter_worker_request_exchange_name (str): Name of the exchange for worker requests.
            _filter_worker_response_exchange_name (str): Name of the exchange for worker responses.
            _filter_worker_request_queue (str): Name of the queue for worker requests.
            _filter_worker_request_routing_key (str): Routing key for worker requests.
            _awaited_delegated_response_ids (set): Set of request IDs for which responses are awaited.
            _collected_response_objects (Dict[str, Dict[Any, Any]]): Dictionary of response objects collected so far.
            _filter_worker_response_queue (str): Name of the queue for worker responses.
            _filter_worker_response_routing_key (str): Routing key for worker responses.
            _rw_lock (aiorwlock.RWLock): Read-write lock for synchronizing access to shared resources.
            _preload_finished_event (asyncio.Event): Event that is set when preloading is complete.
            _redis_conn: Redis connection object.
            _channel: RabbitMQ channel object.
            _q_obj: RabbitMQ queue object.
            _unique_id: Unique identifier for this instance.
            _response_exchange: RabbitMQ exchange object for worker responses.
        """

        self._qos = 1
        self._filter_worker_request_exchange_name = f'{settings.rabbitmq.setup.delegated_worker.exchange}:Request:{settings.namespace}'
        self._filter_worker_response_exchange_name = f'{settings.rabbitmq.setup.delegated_worker.exchange}:Response:{settings.namespace}'
        self._filter_worker_request_queue, \
            self._filter_worker_request_routing_key = get_delegate_worker_request_queue_routing_key()
        # request IDs on which responses are awaited. preloading is complete when this set is empty
        self._awaited_delegated_response_ids = set()
        # epoch ID -> task type/ID (for eg, txHash) -> response object on task (for. eg tx receipt against txHash)
        self._collected_response_objects: Dict[str, Dict[Any, Any]] = defaultdict(dict)
        self._filter_worker_response_queue = None
        self._filter_worker_response_routing_key = None
        self._rw_lock = aiorwlock.RWLock()
        self._preload_finished_event = asyncio.Event()
        self._redis_conn = None
        self._channel = None
        self._q_obj = None
        self._unique_id = None
        self._response_exchange = None

    async def cleanup(self):
        """
        Cleans up the resources used by the delegator preloader.
        Closes the Redis connection and cancels the consumer tag.
        """
        if self._redis_conn:
            try:
                await self._redis_conn.close()
            except Exception as e:
                self._logger.exception('Exception while closing redis connection: {}', e)

        if self._channel and self._q_obj and not self._channel.is_closed:
            await self._q_obj.cancel(self._consumer_tag)
            await self._channel.close()

    async def _periodic_awaited_responses_checker(self):
        """
        Periodically checks for awaited delegated responses and triggers the on_delegated_responses_complete callback
        when all responses have been received.
        """
        _running = True
        while _running:
            await asyncio.sleep(1)
            async with self._rw_lock.reader_lock:
                if len(self._awaited_delegated_response_ids) == 0:
                    await self._on_delegated_responses_complete()
                    self._logger.info('Preloading task {} for epoch {} complete', self._task_type, self._epoch.epochId)
                    _running = False
        self._preload_finished_event.set()

    async def _on_filter_worker_response_message(
        self,
        message: aio_pika.abc.AbstractIncomingMessage,
    ):
        """
        Callback function that is called when a response message is received from the filter worker.

        Args:
            message (aio_pika.abc.AbstractIncomingMessage): The incoming message from the filter worker.
        """
        if message.routing_key.split('.')[-1] != self._unique_id:
            await message.nack(requeue=True)
            return
        else:
            await message.ack()
        asyncio.ensure_future(self._handle_filter_worker_response_message(message.body))

    @retry(
        reraise=True,
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(2),
        wait=wait_random_exponential(multiplier=1, max=3),

    )
    async def compute_with_retry(self, epoch: EpochBase, redis_conn: aioredis.Redis, rpc_helper: RpcHelper):
        """
        Compute with retry logic.

        Args:
            epoch (EpochBase): The epoch to compute.
            redis_conn (aioredis.Redis): The Redis connection.
            rpc_helper (RpcHelper): The RPC helper.

        Returns:
            The result of the computation.
        """
        return await self.compute_with_delegate_workers(epoch=epoch, redis_conn=redis_conn, rpc_helper=rpc_helper)

    async def compute_with_delegate_workers(
            self,
            epoch: EpochBase,
            redis_conn: aioredis.Redis,
            rpc_helper: RpcHelper,
    ):
        """
        Computes the delegated worker responses for the given epoch using RabbitMQ and Redis.

        Args:
            epoch: An instance of EpochBase representing the epoch for which to compute the delegated worker responses.
            redis_conn: An instance of aioredis.Redis representing the Redis connection to use.
            rpc_helper: An instance of RpcHelper representing the RPC helper to use.

        Raises:
            Exception: If the preloading task times out or if an exception occurs while waiting for preloading to complete.
        """
        self._redis_conn = redis_conn
        self._awaited_delegated_response_ids = set(self._request_id_query_obj_map.keys())
        self._unique_id = str(uuid.uuid4())
        async with await get_rabbitmq_basic_connection_async() as rmq_conn:
            self._channel = await rmq_conn.channel()
            await self._channel.set_qos(self._qos)

            self._q_obj = await self._channel.declare_queue(exclusive=True)

            self._filter_worker_response_queue, \
                _filter_worker_response_routing_key_pattern = get_delegate_worker_response_queue_routing_key_pattern()

            self._filter_worker_response_routing_key = _filter_worker_response_routing_key_pattern.replace(
                '*', self._unique_id,
            )

            self._logger.debug(
                'Consuming {} fetch response queue {} '
                'in preloader, with routing key {}',
                self._task_type,
                self._filter_worker_response_queue,
                self._filter_worker_response_routing_key,
            )
            self._response_exchange = await self._channel.get_exchange(
                name=self._filter_worker_response_exchange_name,
            )
            await self._q_obj.bind(self._response_exchange, routing_key=self._filter_worker_response_routing_key)
            self._consumer_tag = await self._q_obj.consume(
                callback=self._on_filter_worker_response_message,
            )
            asyncio.ensure_future(self._periodic_awaited_responses_checker())

            self._exchange = await self._channel.get_exchange(
                name=self._filter_worker_request_exchange_name,
            )
            query_tasks = list()
            for query_obj in self._request_id_query_obj_map.values():
                query_obj.extra['unique_id'] = self._unique_id
                message_data = query_obj.json().encode('utf-8')

                # Prepare a message to send
                queue_message = Message(message_data)

                t = self._exchange.publish(
                    message=queue_message,
                    routing_key=self._filter_worker_request_routing_key,
                )

                query_tasks.append(t)

            self._logger.trace(
                'Queued {} requests by preloader delegator {} for publish to delegated worker over RabbitMQ',
                self._task_type, len(query_tasks),
            )
            asyncio.ensure_future(asyncio.gather(*query_tasks, return_exceptions=True))

            try:
                await asyncio.wait_for(self._preload_finished_event.wait(), timeout=preloader_config.timeout)
                await self.cleanup()
            except asyncio.TimeoutError:
                self._logger.warning(
                    'Preloading task {} for epoch {} timed out after {} seconds',
                    self._task_type, epoch.epochId, preloader_config.timeout,
                )
                await self.cleanup()
                raise Exception(
                    f'Preloading task {self._task_type} for epoch {epoch.epochId} timed out after {preloader_config.timeout} seconds',
                )
            except Exception as e:
                self._logger.warning('Exception while waiting for preloading to complete: {}', e)
                await self.cleanup()
                raise e
