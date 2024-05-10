import asyncio
import functools
from abc import ABC
from abc import ABCMeta
from abc import abstractmethod
from abc import abstractproperty
from typing import Any
from typing import Dict
from typing import Union
from urllib.parse import urljoin

import aio_pika
import loguru._logger
from httpx import AsyncClient
from httpx import Client as SyncClient
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
    """
    Returns a robust connection to RabbitMQ server using the settings specified in the configuration file.
    """
    return await aio_pika.connect_robust(
        host=settings.rabbitmq.host,
        port=settings.rabbitmq.port,
        virtual_host='/',
        login=settings.rabbitmq.user,
        password=settings.rabbitmq.password,
    )


async def get_rabbitmq_basic_connection_async():
    """
    Returns an async connection to RabbitMQ using the settings specified in the config file.

    :return: An async connection to RabbitMQ.
    """
    return await aio_pika.connect(
        host=settings.rabbitmq.host,
        port=settings.rabbitmq.port,
        virtual_host='/',
        login=settings.rabbitmq.user,
        password=settings.rabbitmq.password,
    )


async def get_rabbitmq_channel(connection_pool) -> aio_pika.Channel:
    """
    Acquires a connection from the connection pool and returns a channel object for RabbitMQ communication.

    Args:
        connection_pool: An instance of `aio_pika.pool.Pool`.

    Returns:
        An instance of `aio_pika.Channel`.
    """
    async with connection_pool.acquire() as connection:
        return await connection.channel()


def misc_notification_callback_result_handler(fut: asyncio.Future):
    """
    Handles the result of a callback or notification.

    Args:
        fut (asyncio.Future): The future object representing the callback or notification.

    Returns:
        None
    """
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


def sync_notification_callback_result_handler(f: functools.partial):
    """
    Handles the result of a synchronous notification callback.

    Args:
        f (functools.partial): The function to handle.

    Returns:
        None
    """
    try:
        result = f()
    except Exception as exc:
        if settings.logs.trace_enabled:
            logger.opt(exception=True).error(
                'Exception while sending callback or notification: {}', exc,
            )
        else:
            logger.error('Exception while sending callback or notification: {}', exc)
    else:
        logger.debug('Callback or notification result:{}', result)


async def send_failure_notifications_async(client: AsyncClient, message: BaseModel):
    """
    Sends failure notifications to the configured reporting services.

    Args:
        client (AsyncClient): The async HTTP client to use for sending notifications.
        message (BaseModel): The message to send as notification.

    Returns:
        None
    """
    if settings.reporting.service_url:
        f = asyncio.ensure_future(
            client.post(
                url=urljoin(settings.reporting.service_url, '/reportIssue'),
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


def send_failure_notifications_sync(client: SyncClient, message: BaseModel):
    """
    Sends failure notifications synchronously to the reporting service and/or Slack.

    Args:
        client (SyncClient): The HTTP client to use for sending notifications.
        message (BaseModel): The message to send as notification.

    Returns:
        None
    """
    if settings.reporting.service_url:
        f = functools.partial(
            client.post,
            url=urljoin(settings.reporting.service_url, '/reportIssue'),
            json=message.dict(),
        )
        sync_notification_callback_result_handler(f)

    if settings.reporting.slack_url:
        f = functools.partial(
            client.post,
            url=settings.reporting.slack_url,
            json=message.dict(),
        )
        sync_notification_callback_result_handler(f)


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
        redis_conn: aioredis.Redis,
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
