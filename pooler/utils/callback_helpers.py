import time
from abc import ABC
from abc import ABCMeta
from abc import abstractmethod
from abc import abstractproperty
from functools import wraps
from urllib.parse import urljoin

import aio_pika
from httpx import AsyncClient
from redis import asyncio as aioredis
from tenacity import AsyncRetrying
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential

from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.models.data_models import PayloadCommitAPIRequest
from pooler.utils.models.data_models import SnapshotterIssue
from pooler.utils.models.data_models import SnapshotterIssueSeverity
from pooler.utils.models.message_models import PowerloomCallbackProcessMessage
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


def notify_on_task_failure(fn):
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            await fn(self, *args, **kwargs)

        except Exception as e:
            # Logging the error trace
            logger.opt(exception=True).error(f'Error: {e}')

            # Sending the error details to the issue reporting service
            try:
                if 'msg_obj' in kwargs:
                    msg_obj = kwargs['msg_obj']
                    if isinstance(msg_obj, PowerloomCallbackProcessMessage):
                        contract = msg_obj.contract
                        project_id = f'uniswap_pairContract_*_{contract}_{settings.namespace}'

                await self._client.post(
                    url=settings.issue_report_url,
                    json=SnapshotterIssue(
                        instanceID=settings.instance_id,
                        severity=SnapshotterIssueSeverity.medium,
                        issueType='MISSED_SNAPSHOT',
                        projectID=project_id if project_id else '*',
                        timeOfReporting=int(time.time()),
                        extra={'issueDetails': f'Error : {e}'},
                        serviceName='Pooler|PairTotalReservesProcessor',
                    ).dict(),
                )
            except Exception as err:
                # Logging the error trace if service is not able to report issue
                logger.opt(exception=True).error(f'Error: {err}')

    return wrapper


class AuditProtocolCommandsHelper:
    @classmethod
    async def commit_payload(
        cls, report_payload: PayloadCommitAPIRequest, session: AsyncClient,
    ):
        async for attempt in AsyncRetrying(
            reraise=False,
            stop=stop_after_attempt(settings.audit_protocol_engine.retry),
            wait=wait_random_exponential(multiplier=2, max=10),
        ):
            with attempt:
                response_obj = await session.post(
                    url=urljoin(
                        settings.audit_protocol_engine.url, 'commit_payload',
                    ),
                    json=report_payload.dict(),
                )
                response_status_code = response_obj.status_code
                response = response_obj.json() or {}
                if response_status_code in range(200, 300):
                    return response
                elif (
                    attempt.retry_state.attempt_number ==
                    settings.audit_protocol_engine.retry
                ):
                    if (
                        attempt.retry_state.outcome and
                        attempt.retry_state.outcome.exception()
                    ):
                        raise attempt.retry_state.outcome.exception()
                    else:
                        raise Exception(
                            (
                                'Failed audit protocol engine call with status'
                                f' code: {response_status_code} and response:'
                                f' {response}'
                            ),
                        )
                else:
                    raise Exception(
                        (
                            'Failed audit protocol engine call with status'
                            f' code: {response_status_code} and response:'
                            f' {response}'
                        ),
                    )


class GenericProcessor(ABC):
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
