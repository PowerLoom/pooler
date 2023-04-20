import time
from abc import ABC
from abc import ABCMeta
from abc import abstractmethod
from abc import abstractproperty
from functools import wraps

import aio_pika
from redis import asyncio as aioredis

from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.models.data_models import SnapshotterIssue
from pooler.utils.models.data_models import SnapshotterIssueSeverity
from pooler.utils.models.message_models import PowerloomAggregateFinalizedMessage
from pooler.utils.models.message_models import PowerloomIndexFinalizedMessage
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


def notify_on_task_failure_snapshot(fn):
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            await fn(self, *args, **kwargs)

        except Exception as e:
            # Logging the error trace
            logger.opt(exception=True).error(f'Error: {e}')
            logger.error('Sending Missed Snapshot Error to Issue Reporting Service')

            # Sending the error details to the issue reporting service
            try:
                if 'task_type' in kwargs:
                    task_type = kwargs['task_type']
                else:
                    task_type = 'unknown'

                projectId = None
                if 'msg_obj' in kwargs:
                    msg_obj = kwargs['msg_obj']
                    if isinstance(msg_obj, PowerloomSnapshotProcessMessage):
                        contract = msg_obj.contract
                        project_id = f'{task_type}_{contract}_{settings.namespace}'

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
                )
            except Exception as err:
                # Logging the error trace if service is not able to report issue
                logger.opt(exception=True).error(f'Error: Unable to report the issue, got: {err}')

    return wrapper


def notify_on_task_failure_aggregate(fn):
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            await fn(self, *args, **kwargs)

        except Exception as e:
            # Logging the error trace
            logger.opt(exception=True).error(f'Error: {e}')
            logger.error('Sending Missed Snapshot Error to Issue Reporting Service')

            # Sending the error details to the issue reporting service
            try:
                if 'task_type' in kwargs:
                    task_type = kwargs['task_type']
                else:
                    task_type = 'unknown'

                project_id = None
                if 'msg_obj' in kwargs:
                    msg_obj = kwargs['msg_obj']
                    project_id = f'{task_type}_{msg_obj.projectId}_{settings.namespace}'

                await self._client.post(
                    url=settings.issue_report_url,
                    json=SnapshotterIssue(
                        instanceID=settings.instance_id,
                        severity=SnapshotterIssueSeverity.medium,
                        issueType='MISSED_SNAPSHOT',
                        projectID=project_id if project_id else '*',
                        timeOfReporting=int(time.time()),
                        extra={'issueDetails': f'Error : {e}'},
                        serviceName='Pooler|AggregateWorker',
                    ).dict(),
                )
            except Exception as err:
                # Logging the error trace if service is not able to report issue
                logger.opt(exception=True).error(f'Error: Unable to report the issue, got: {err}')

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
        redis: aioredis,
        rpc_helper: RpcHelper,
    ):
        pass


class GenericProcessorIndexBasedAggregate(ABC):
    __metaclass__ = ABCMeta

    def __init__(self):
        pass

    @abstractproperty
    def transformation_lambdas(self):
        pass

    @abstractmethod
    async def compute(
        self,
        msg_obj: PowerloomIndexFinalizedMessage,
        redis: aioredis,
        rpc_helper: RpcHelper,
    ):
        pass


class GenericProcessorAggregateBasedAggregate(ABC):
    __metaclass__ = ABCMeta

    def __init__(self):
        pass

    @abstractproperty
    def transformation_lambdas(self):
        pass

    @abstractmethod
    async def compute(
        self,
        msg_obj: PowerloomAggregateFinalizedMessage,
        redis: aioredis,
        rpc_helper: RpcHelper,
    ):
        pass
