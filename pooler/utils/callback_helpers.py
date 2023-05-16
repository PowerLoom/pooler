import asyncio
import hashlib
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
                logger.error(
                    'Error constructing snapshot against message {} for task type {} : {}', msg_obj, task_type, e,
                )

            # Sending the error details to the issue reporting service
            contract = msg_obj.contract
            epoch_id = msg_obj.epochId
            project_id = f'{task_type}:{contract}:{settings.namespace}'

            if settings.reporting.service_url:
                f = asyncio.ensure_future(
                    await self._client.post(
                        url=settings.reporting.service_url,
                        json=SnapshotterIssue(
                            instanceID=settings.instance_id,
                            issueType='MISSED_SNAPSHOT',
                            projectID=project_id,
                            epochId=epoch_id,
                            timeOfReporting=int(time.time()),
                            extra={'issueDetails': f'Error : {e}'},
                        ).dict(),
                    ),
                )
                f.add_done_callback(misc_notification_callback_result_handler)

            if settings.reporting.slack_url:
                f = asyncio.ensure_future(
                    await self._client.post(
                        url=settings.reporting.slack_url,
                        json=SnapshotterIssue(
                            instanceID=settings.instance_id,
                            issueType='MISSED_SNAPSHOT',
                            projectID=project_id,
                            epochId=epoch_id,
                            timeOfReporting=int(time.time()),
                            extra={'issueDetails': f'Error : {e}'},
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
                    'Error constructing snapshot or aggregate against message {} for task type {} : {}',
                    msg_obj, task_type, e,
                )
            else:
                logger.error(
                    'Error constructing snapshot against message {} for task type {} : {}',
                    msg_obj, task_type, e,
                )

            # Sending the error details to the issue reporting service
            if isinstance(msg_obj, PowerloomCalculateAggregateMessage):
                underlying_project_ids = [project.projectId for project in msg_obj.messages]
                unique_project_id = ''.join(sorted(underlying_project_ids))

                project_hash = hashlib.sha3_256(unique_project_id.encode()).hexdigest()

                project_id = f'{type_}:{project_hash}:{settings.namespace}'

            elif isinstance(msg_obj, PowerloomSnapshotFinalizedMessage):
                contract = msg_obj.projectId.split(':')[-2]
                project_id = f'{type_}:{contract}:{settings.namespace}'

            else:
                project_id = 'UNKNOWN'

            if settings.reporting.service_url:
                f = asyncio.ensure_future(
                    await self._client.post(
                        url=settings.reporting.service_url,
                        json=SnapshotterIssue(
                            instanceID=settings.instance_id,
                            issueType='MISSED_SNAPSHOT',
                            projectID=project_id,
                            epochId=epoch_id,
                            timeOfReporting=int(time.time()),
                            extra={'issueDetails': f'Error : {e}'},
                        ).dict(),
                    ),
                )
                f.add_done_callback(misc_notification_callback_result_handler)

            if settings.reporting.slack_url:
                f = asyncio.ensure_future(
                    await self._client.post(
                        url=settings.reporting.slack_url,
                        json=SnapshotterIssue(
                            instanceID=settings.instance_id,
                            issueType='MISSED_SNAPSHOT',
                            projectID=project_id,
                            epochId=epoch_id,
                            timeOfReporting=int(time.time()),
                            extra={'issueDetails': f'Error : {e}'},
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
