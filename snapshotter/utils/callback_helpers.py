import asyncio
from abc import ABC
from abc import ABCMeta
from abc import abstractmethod
from abc import abstractproperty
from typing import Any
from typing import Dict
from typing import Union

import aio_pika
import loguru._logger
from httpx import AsyncClient
from ipfs_client.main import AsyncIPFSClient
from pydantic import BaseModel
from redis import asyncio as aioredis

from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import logger
from snapshotter.utils.models.message_models import EpochBase
from snapshotter.utils.models.message_models import PowerloomCalculateAggregateMessage
from snapshotter.utils.models.message_models import PowerloomDelegateWorkerRequestMessage
from snapshotter.utils.models.message_models import PowerloomSnapshotProcessMessage
from snapshotter.utils.models.message_models import PowerloomSnapshotSubmittedMessage
from snapshotter.utils.rpc import RpcHelper

# setup logger
helper_logger = logger.bind(module='Powerloom|Callback|Helpers')


async def get_rabbitmq_robust_connection_async():
    return await aio_pika.connect_robust(
        host=settings.rabbitmq.host,
        port=settings.rabbitmq.port,
        virtual_host='/',
        login=settings.rabbitmq.user,
        password=settings.rabbitmq.password,
    )


async def get_rabbitmq_basic_connection_async():
    return await aio_pika.connect(
        host=settings.rabbitmq.host,
        port=settings.rabbitmq.port,
        virtual_host='/',
        login=settings.rabbitmq.user,
        password=settings.rabbitmq.password,
    )


async def get_rabbitmq_channel(connection_pool) -> aio_pika.Channel:
    async with connection_pool.acquire() as connection:
        return await connection.channel()


def misc_notification_callback_result_handler(fut: asyncio.Future):
    try:
        r = fut.result()
    except Exception as e:
        if settings.logs.trace_enabled:
            logger.opt(exception=True).error(
                'Exception while sending callback or notification: {}', e,
            )
        else:
            logger.error('Exception while sending callback or notification: {}', e)
    else:
        logger.debug('Callback or notification result:{}', r)


async def send_failure_notifications(client: AsyncClient, message: BaseModel):
    if settings.reporting.service_url:
        f = asyncio.ensure_future(
            client.post(
                url=settings.reporting.service_url,
                json=message.dict(),
            ),
        )
        f.add_done_callback(misc_notification_callback_result_handler)

    if settings.reporting.slack_url:
        f = asyncio.ensure_future(
            client.post(
                url=settings.reporting.slack_url,
                json=message.dict(),
            ),
        )
        f.add_done_callback(misc_notification_callback_result_handler)


class GenericProcessorSnapshot(ABC):
    __metaclass__ = ABCMeta

    def __init__(self):
        pass

    @abstractproperty
    def transformation_lambdas(self):
        pass

    @abstractmethod
    async def compute(
        self,
        epoch: PowerloomSnapshotProcessMessage,
        redis: aioredis.Redis,
        rpc_helper: RpcHelper,
    ):
        pass


class GenericPreloader(ABC):
    __metaclass__ = ABCMeta

    def __init__(self):
        pass

    @abstractmethod
    async def compute(
        self,
        epoch: EpochBase,
        redis_conn: aioredis.Redis,
        rpc_helper: RpcHelper,
    ):
        pass

    @abstractmethod
    async def cleanup(self):
        pass


class GenericDelegatorPreloader(GenericPreloader):
    _epoch: EpochBase
    _channel: aio_pika.abc.AbstractChannel
    _exchange: aio_pika.abc.AbstractExchange
    _q_obj: aio_pika.abc.AbstractQueue
    _consumer_tag: str
    _redis_conn: aioredis.Redis
    _task_type: str
    _epoch_id: int
    _preload_successful_event: asyncio.Event
    _awaited_delegated_response_ids: set
    _collected_response_objects: Dict[int, Dict[str, Dict[Any, Any]]]
    _logger: loguru._logger.Logger
    _request_id_query_obj_map: Dict[int, Any]

    @abstractmethod
    async def _on_delegated_responses_complete(self):
        pass

    @abstractmethod
    async def _on_filter_worker_response_message(
        self,
        message: aio_pika.abc.AbstractIncomingMessage,
    ):
        pass

    @abstractmethod
    async def _handle_filter_worker_response_message(self, message_body: bytes):
        pass

    @abstractmethod
    async def _periodic_awaited_responses_checker(self):
        pass


class GenericDelegateProcessor(ABC):
    __metaclass__ = ABCMeta

    def __init__(self):
        pass

    @abstractmethod
    async def compute(
        self,
        msg_obj: PowerloomDelegateWorkerRequestMessage,
        redis_conn: aioredis.Redis,
        rpc_helper: RpcHelper,
    ):
        pass


class GenericProcessorAggregate(ABC):
    __metaclass__ = ABCMeta

    def __init__(self):
        pass

    @abstractproperty
    def transformation_lambdas(self):
        pass

    @abstractmethod
    async def compute(
        self,
        msg_obj: Union[PowerloomSnapshotSubmittedMessage, PowerloomCalculateAggregateMessage],
        redis: aioredis.Redis,
        rpc_helper: RpcHelper,
        anchor_rpc_helper: RpcHelper,
        ipfs_reader: AsyncIPFSClient,
        protocol_state_contract,
        project_id: str,
    ):
        pass