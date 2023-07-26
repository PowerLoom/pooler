import asyncio
from collections import defaultdict
from typing import Any
from typing import Dict

import aio_pika
import aiorwlock
from aio_pika import Message
from redis import asyncio as aioredis

from snapshotter.init_rabbitmq import get_delegate_worker_request_queue_routing_key
from snapshotter.init_rabbitmq import get_delegate_worker_response_queue_routing_key_pattern
from snapshotter.settings.config import settings
from snapshotter.utils.callback_helpers import GenericDelegatorPreloader
from snapshotter.utils.callback_helpers import get_rabbitmq_basic_connection_async
from snapshotter.utils.models.message_models import EpochBase
from snapshotter.utils.rpc import RpcHelper


class DelegatorPreloaderAsyncWorker(GenericDelegatorPreloader):
    def __init__(self, **kwargs):
        self._qos = 10
        self._filter_worker_exchange_name = f'{settings.rabbitmq.setup.delegated_worker.exchange}:{settings.namespace}'
        self._filter_worker_request_queue, \
            self._filter_worker_request_routing_key = get_delegate_worker_request_queue_routing_key()
        # request IDs on which responses are awaited. preloading is complete when this set is empty
        self._awaited_delegated_response_ids = set()
        # epoch ID -> task type/ID (for eg, txHash) -> response object on task (for. eg tx receipt against txHash)
        self._collected_response_objects: Dict[int, Dict[str, Dict[Any, Any]]] = defaultdict(dict)
        self._filter_worker_response_queue = None
        self._filter_worker_response_routing_key = None
        self._rw_lock = aiorwlock.RWLock()
        self._preload_successful_event = asyncio.Event()
        self._cleanup_done = False

    async def cleanup(self):
        if self._cleanup_done:
            return
        try:
            await self._redis_conn.close()
        except Exception as e:
            self._logger.exception('Exception while closing redis connection: {}', e)

    async def _periodic_awaited_responses_checker(self):
        _running = True
        while _running:
            await asyncio.sleep(1)
            async with self._rw_lock.reader_lock:
                if len(self._awaited_delegated_response_ids) == 0:
                    await self._on_delegated_responses_complete()
                    self._logger.info('Preloading task {} for epoch {} complete', self._task_type, self._epoch.epochId)
                    _running = False
        self._preload_successful_event.set()

    async def _on_filter_worker_response_message(
        self,
        message: aio_pika.abc.AbstractIncomingMessage,
    ):
        if message.routing_key.split('.')[-1] != f'{self._epoch.epochId}_{self._task_type}':
            await message.nack(requeue=True)
            return
        else:
            await message.ack()
        asyncio.ensure_future(self._handle_filter_worker_response_message(message.body))

    async def compute(
            self,
            epoch: EpochBase,
            redis_conn: aioredis.Redis,
            rpc_helper: RpcHelper,
    ):
        self._awaited_delegated_response_ids = set(self._request_id_query_obj_map.keys())
        async with await get_rabbitmq_basic_connection_async() as rmq_conn:
            self._channel = await rmq_conn.channel()
            await self._channel.set_qos(10)
            self._exchange = await self._channel.get_exchange(
                name=self._filter_worker_exchange_name,
            )
            query_tasks = list()
            for query_obj in self._request_id_query_obj_map.values():
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

            self._filter_worker_response_queue, \
                _filter_worker_response_routing_key_pattern = get_delegate_worker_response_queue_routing_key_pattern()

            self._filter_worker_response_routing_key = _filter_worker_response_routing_key_pattern.replace(
                '*', f'{epoch.epochId}_{self._task_type}',
            )

            self._q_obj = await self._channel.declare_queue(exclusive=True)

            self._logger.debug(
                'Consuming {} fetch response queue {} '
                'in preloader, with routing key {}',
                self._task_type,
                self._filter_worker_response_queue,
                self._filter_worker_response_routing_key,
            )
            await self._q_obj.bind(self._exchange, routing_key=self._filter_worker_response_routing_key)
            self._consumer_tag = await self._q_obj.consume(
                callback=self._on_filter_worker_response_message,
            )
            asyncio.ensure_future(self._periodic_awaited_responses_checker())

            await self._preload_successful_event.wait()  # will block until preload is completed
