import asyncio
import time
from abc import ABC
from abc import ABCMeta
from abc import abstractmethod
from abc import abstractproperty
from functools import wraps

import aio_pika
from ipfs_client.main import AsyncIPFSClient
from redis import asyncio as aioredis

from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.models.data_models import SnapshotterIssue
from pooler.utils.models.data_models import SnapshotterIssueSeverity
from pooler.utils.models.message_models import PowerloomCalculateAggregateMessage
from pooler.utils.models.message_models import PowerloomSnapshotFinalizedMessage
from pooler.utils.models.message_models import PowerloomSnapshotProcessMessage
from pooler.utils.rpc import RpcHelper

# setup logger
helper_logger = logger.bind(module='PowerLoom|Callback|Helpers')


async def get_rabbitmq_connection():
    return await aio_pika.connect_robust(
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


# TODO: Update notification flow, send directly to slack and a copy to issue reporting service
# (offchain consensus for now)


def notify_on_task_failure_snapshot(fn):
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            await fn(self, *args, **kwargs)
        except Exception as e:
            # Logging the error trace
            msg_obj: PowerloomSnapshotProcessMessage = kwargs['msg_obj'] if 'msg_obj' in kwargs else args[0]
            task_type = args[1]
            if settings.logs.trace_enabled:
                logger.opt(exception=True).error(
                    'Error constructing snapshot against message {} for task type {} : {}', msg_obj, task_type, e,
                )
            else:
                logger.error('Error constructing snapshot against message {} for task type {} : {}', msg_obj, task_type, e)

            # Sending the error details to the issue reporting service
            contract = msg_obj.contract
            project_id = f'{task_type}_{contract}_{settings.namespace}'

            f = asyncio.ensure_future(
                await self._client.post(
                    url=settings.issue_report_url,
                    json=SnapshotterIssue(
                        instanceID=settings.instance_id,
                        severity=SnapshotterIssueSeverity.medium,
                        issueType='MISSED_SNAPSHOT',
                        projectID=project_id if project_id else '*',
                        timeOfReporting=int(time.time()),
                        extra={'issueDetails': f'Error : {e}'},
                        serviceName='Pooler|SnapshotWorker',
                    ).dict(),
                ),
            )
            f.add_done_callback(misc_notification_callback_result_handler)
    return wrapper


def notify_on_task_failure_aggregate(fn):
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            await fn(self, *args, **kwargs)

        except Exception as e:
            msg_obj = kwargs['msg_obj'] if 'msg_obj' in kwargs else args[0]
            task_type = args[1]
            # Logging the error trace
            if settings.logs.trace_enabled:
                logger.opt(exception=True).error(
                    'Error constructing snapshot or aggregate against message {} for task type {} : {}', msg_obj, task_type, e,
                )
            else:
                logger.error('Error constructing snapshot against message {} for task type {} : {}', msg_obj, task_type, e)

            # Sending the error details to the issue reporting service
            if isinstance(msg_obj, PowerloomCalculateAggregateMessage):
                project_id = f'{task_type}_*_{settings.namespace}'
            elif isinstance(msg_obj, PowerloomSnapshotFinalizedMessage):
                project_id = f'{task_type}_{msg_obj.projectId}_{settings.namespace}'
            else:
                project_id = f'{task_type}_{settings.namespace}'

            f = asyncio.ensure_future(
                await self._client.post(
                    url=settings.issue_report_url,
                    json=SnapshotterIssue(
                        instanceID=settings.instance_id,
                        severity=SnapshotterIssueSeverity.medium,
                        issueType='MISSED_SNAPSHOT',
                        projectID=project_id,
                        timeOfReporting=int(time.time()),
                        extra={'issueDetails': f'Error : {e}'},
                        serviceName='Pooler|AggregateWorker',
                    ).dict(),
                ),
            )
            f.add_done_callback(misc_notification_callback_result_handler)

    return wrapper


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
        min_chain_height: int,
        max_chain_height: int,
        data_source_contract_address: str,
        redis: aioredis.Redis,
        rpc_helper: RpcHelper,
    ):
        pass


class GenericProcessorSingleProjectAggregate(ABC):
    __metaclass__ = ABCMeta

    def __init__(self):
        pass

    @abstractproperty
    def transformation_lambdas(self):
        pass

    @abstractmethod
    async def compute(
        self,
        msg_obj: PowerloomSnapshotFinalizedMessage,
        redis: aioredis.Redis,
        rpc_helper: RpcHelper,
        anchor_rpc_helper: RpcHelper,
        ipfs_reader: AsyncIPFSClient,
        protocol_state_contract,
        project_id: str,
    ):
        pass


class GenericProcessorMultiProjectAggregate(ABC):
    __metaclass__ = ABCMeta

    def __init__(self):
        pass

    @abstractproperty
    def transformation_lambdas(self):
        pass

    @abstractmethod
    async def compute(
        self,
        msg_obj: PowerloomCalculateAggregateMessage,
        redis: aioredis.Redis,
        rpc_helper: RpcHelper,
        anchor_rpc_helper: RpcHelper,
        ipfs_reader: AsyncIPFSClient,
        protocol_state_contract,
        project_id: str,

    ):
        pass
