from httpx import AsyncClient
from callback_modules.data_models import PayloadCommitAPIRequest
from urllib.parse import urljoin
from dynaconf import settings
from eth_utils import keccak
from setproctitle import setproctitle
from functools import partial
from loguru import logger
from uuid import uuid4
from redis_conn import RedisPoolCache
from aio_pika import IncomingMessage
from aio_pika.pool import Pool
from typing import Union, Dict
import sys
import resource
from redis import asyncio as aioredis
import requests
import logging
import logging.handlers
import redis
import multiprocessing
import asyncio
import signal
import aio_pika
from tenacity import AsyncRetrying, stop_after_attempt, wait_random_exponential


async def get_rabbitmq_connection():
    return await aio_pika.connect_robust(
        host=settings.RABBITMQ.HOST,
        port=settings.RABBITMQ.PORT,
        virtual_host='/',
        login=settings.RABBITMQ.USER,
        password=settings.RABBITMQ.PASSWORD
    )


async def get_rabbitmq_channel(connection_pool) -> aio_pika.Channel:
    async with connection_pool.acquire() as connection:
        return await connection.channel()


class AuditProtocolCommandsHelper:
    @classmethod
    def set_commit_callback_url(cls, pair_contract_address, stream, redis_conn: aioredis.Redis):
        project_id = f'uniswap_pairContract_{stream}_{pair_contract_address}_{settings.NAMESPACE}'
        if not redis_conn.sismember(f'uniswap:{settings.NAMESPACE}:callbackURLSetFor', project_id):
            r = requests.post(
                url=urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL, f'/{project_id}/confirmations/callback'),
                json={
                    'callbackURL': urljoin(settings.WEBHOOK_LISTENER.ROOT,
                                           settings.WEBHOOK_LISTENER.COMMIT_CONFIRMATION_CALLBACK_PATH)
                },
                headers={'X-API-KEY': settings.NAMESPACE}
            )
            if r.status_code in range(200, 300):
                redis_conn.sadd(f'uniswap:{settings.NAMESPACE}:callbackURLSetFor', project_id)

    @classmethod
    async def commit_payload(cls, report_payload: PayloadCommitAPIRequest, session: AsyncClient):
        async for attempt in AsyncRetrying(
                reraise=False,
                stop=stop_after_attempt(settings.AUDIT_PROTOCOL_ENGINE.RETRY),
                wait=wait_random_exponential(multiplier=2, max=10)
        ):
            with attempt:
                response_obj = await session.post(
                        url=urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL, 'commit_payload'),
                        json=report_payload.dict(),
                        headers={'X-API-KEY': settings.NAMESPACE}
                )
                response_status_code = response_obj.status_code
                response = response_obj.json() or {}
                if response_status_code in range(200, 300):
                    return response
                elif attempt.retry_state.attempt_number == settings.AUDIT_PROTOCOL_ENGINE.RETRY:
                    if attempt.retry_state.outcome and attempt.retry_state.outcome.exception():
                        raise attempt.retry_state.outcome.exception()
                    else:
                        raise Exception(
                            'Failed audit protocol engine call with status code: %s and response: %s',
                            response_status_code, response
                        )
                else:
                    raise Exception(
                        'Failed audit protocol engine call with status code: %s and response: %s',
                        response_status_code, response
                    )


class CallbackAsyncWorker(multiprocessing.Process):
    def __init__(self, name, rmq_q, rmq_routing, **kwargs):
        self._core_rmq_consumer: asyncio.Task
        self._q = rmq_q
        self._rmq_routing = rmq_routing
        self._unique_id = f'{name}-' + keccak(text=str(uuid4())).hex()[:8]
        self._aioredis_pool = None
        self._redis_conn: Union[None, aioredis.Redis] = None
        self._running_callback_tasks: Dict[str, asyncio.Task] = dict()
        super(CallbackAsyncWorker, self).__init__(name=name, **kwargs)
        self._logger = logging.getLogger(self.name)
        self._logger.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(levelname)-8s %(name)-4s %(asctime)s %(msecs)d %(module)s-%(funcName)s: %(message)s")
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(logging.DEBUG)
        stdout_handler.setFormatter(formatter)
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.ERROR)
        stderr_handler.setFormatter(formatter)
        # self._logger.debug('Launched %s ', self._unique_id)
        # self._logger.debug('Launched PID: %s', self.pid)
        self._logger.handlers = [
            logging.handlers.SocketHandler(host=settings.get('LOGGING_SERVER.HOST', 'localhost'),
                                           port=settings.get('LOGGING_SERVER.PORT',
                                                             logging.handlers.DEFAULT_TCP_LOGGING_PORT)),
            stdout_handler, stderr_handler
        ]
        # logger.add(
        #     sink='logs/' + self._unique_id + '_{time}.log', rotation='20MB', retention=20, compression='gz'
        # )
        # setup_loguru_intercept()
        self._shutdown_signal_received_count = 0

    async def _shutdown_handler(self, sig, loop: asyncio.AbstractEventLoop):
        self._shutdown_signal_received_count += 1
        if self._shutdown_signal_received_count > 1:
            self._logger.info(
                f'Received exit signal {sig.name}. Not processing as shutdown sequence was already initiated...')
        else:
            self._logger.info(
                f'Received exit signal {sig.name}. Processing shutdown sequence...')
            # check the done or cancelled status of self._running_callback_tasks.values()
            for u_uid, t in self._running_callback_tasks.items():
                self._logger.debug(
                    'Shutdown handler: Checking result and status of aio_pika consumer callback task %s', t.get_name()
                )
                try:
                    task_result = t.result()
                except asyncio.CancelledError:
                    self._logger.info(
                        'Shutdown handler: aio_pika consumer callback task %s was cancelled', t.get_name()
                    )
                except asyncio.InvalidStateError:
                    self._logger.info(
                        'Shutdown handler: aio_pika consumer callback task %s result not available yet. '
                        'Still running.',
                        t.get_name()
                    )
                except Exception as e:
                    self._logger.info(
                        'Shutdown handler: aio_pika consumer callback task %s raised Exception. '
                        '%s',
                        t.get_name(), e
                    )
                else:
                    self._logger.info(
                        'Shutdown handler: aio_pika consumer callback task returned with result %s',
                        t.get_name(),
                        task_result
                    )
            # await asyncio.gather(*self._running_callback_tasks.values(), return_exceptions=True)

            tasks = [t for t in asyncio.all_tasks(loop) if t is not
                     asyncio.current_task(loop)]

            [task.cancel() for task in tasks]

            self._logger.info(f'Cancelling {len(tasks)} outstanding tasks')
            await asyncio.gather(*tasks, return_exceptions=True)
            loop.stop()
            self._logger.info('Shutdown complete.')

    async def _rabbitmq_consumer(self, loop):
        self._rmq_connection_pool = Pool(get_rabbitmq_connection, max_size=5, loop=loop)
        self._rmq_channel_pool = Pool(partial(get_rabbitmq_channel, self._rmq_connection_pool), max_size=20,
                                      loop=loop)
        async with self._rmq_channel_pool.acquire() as channel:
            await channel.set_qos(20)
            q_obj = await channel.get_queue(
                name=self._q,
                ensure=False
            )
            self._logger.debug(f'Consuming queue {self._q} with routing key {self._rmq_routing}...')
            await q_obj.consume(self._on_rabbitmq_message)

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        await message.ack()

    async def init_redis_pool(self):
        if not self._aioredis_pool:
            self._aioredis_pool = RedisPoolCache()
            await self._aioredis_pool.populate()
            # RedisPoolCache.append_ssl_connection_params(REDIS_CONN_CONF, settings['redis'])
            self._redis_conn = self._aioredis_pool._aioredis_pool

    def run(self) -> None:
        setproctitle(self._unique_id)
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (settings['rlimit']['file_descriptors'], hard))
        # logging.config.dictConfig(config_logger_with_namespace(self.name))
        self._logger = logging.getLogger(self.name)
        self._logger.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(levelname)-8s %(name)-4s %(asctime)s %(msecs)d %(module)s-%(funcName)s: %(message)s")
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(logging.DEBUG)
        stdout_handler.setFormatter(formatter)
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.ERROR)
        stderr_handler.setFormatter(formatter)
        # self._logger.debug('Launched %s ', self._unique_id)
        # self._logger.debug('Launched PID: %s', self.pid)
        self._logger.handlers = [
            logging.handlers.SocketHandler(host=settings.get('LOGGING_SERVER.HOST','localhost'),
            port=settings.get('LOGGING_SERVER.PORT',logging.handlers.DEFAULT_TCP_LOGGING_PORT)),
            stdout_handler, stderr_handler
        ]
        ev_loop = asyncio.get_event_loop()
        signals = (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT)
        for s in signals:
            ev_loop.add_signal_handler(
                s, lambda x=s: ev_loop.create_task(self._shutdown_handler(x, ev_loop)))
        self._logger.debug(f'Starting asynchronous epoch callback worker {self._unique_id}...')
        self._core_rmq_consumer = asyncio.ensure_future(self._rabbitmq_consumer(ev_loop))
        try:
            ev_loop.run_forever()
        finally:
            ev_loop.close()
