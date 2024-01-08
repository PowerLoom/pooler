import asyncio
import functools
from abc import ABC
from abc import ABCMeta
from abc import abstractmethod
from urllib.parse import urljoin

from httpx import AsyncClient
from httpx import Client as SyncClient
from ipfs_client.main import AsyncIPFSClient
from pydantic import BaseModel

from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import logger
from snapshotter.utils.models.message_models import EpochBase
from snapshotter.utils.models.message_models import SnapshotProcessMessage
from snapshotter.utils.rpc import RpcHelper

# setup logger
helper_logger = logger.bind(module='Callback|Helpers')


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


class GenericProcessor(ABC):
    __metaclass__ = ABCMeta

    def __init__(self):
        pass

    @abstractmethod
    async def compute(
        self,
        msg_obj: SnapshotProcessMessage,
        rpc_helper: RpcHelper,
        anchor_rpc_helper: RpcHelper,
        ipfs_reader: AsyncIPFSClient,
        protocol_state_contract,
    ):
        pass
