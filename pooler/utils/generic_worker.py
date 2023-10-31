import asyncio
import multiprocessing
import resource
import signal
from functools import partial
from typing import Dict
from typing import Union
from uuid import uuid4

from aio_pika import IncomingMessage
from aio_pika.pool import Pool
from eth_utils import keccak
from httpx import AsyncClient
from httpx import AsyncHTTPTransport
from httpx import Limits
from httpx import Timeout
from redis import asyncio as aioredis
from setproctitle import setproctitle
from web3 import Web3

from pooler.settings.config import settings
from pooler.utils.callback_helpers import get_rabbitmq_channel
from pooler.utils.callback_helpers import get_rabbitmq_connection
from pooler.utils.default_logger import logger
from pooler.utils.file_utils import read_json_file
from pooler.utils.redis.redis_conn import RedisPoolCache
from pooler.utils.rpc import RpcHelper


class GenericAsyncWorker(multiprocessing.Process):
    _async_transport: AsyncHTTPTransport
    _rmq_connection_pool: Pool
    _rmq_channel_pool: Pool
    _aioredis_pool: aioredis.Redis
    _writer_redis_pool: aioredis.Redis
    _reader_redis_pool: aioredis.Redis
    _rpc_helper: RpcHelper
    _httpx_client: AsyncClient

    def __init__(self, name, **kwargs):
        self._core_rmq_consumer: asyncio.Task
        self._exchange_name = (
            f"{settings.rabbitmq.setup.callbacks.exchange}:{settings.namespace}"
        )
        self._unique_id = f"{name}-" + keccak(text=str(uuid4())).hex()[:8]
        self._redis_conn: Union[None, aioredis.Redis] = None
        self._running_callback_tasks: Dict[str, asyncio.Task] = dict()
        super(GenericAsyncWorker, self).__init__(name=name, **kwargs)
        self._logger = logger.bind(module=self.name)
        self._aioredis_pool = None
        self._async_transport = None
        self._rpc_helper = None
        self._anchor_rpc_helper = None
        self.protocol_state_contract = None

        self._rate_limiting_lua_scripts = None
        self._shutdown_signal_received_count = 0

        self.protocol_state_contract_abi = read_json_file(
            settings.protocol_state.abi,
            self._logger,
        )
        self.protocol_state_contract_address = settings.protocol_state.address

    async def _shutdown_handler(self, sig, loop: asyncio.AbstractEventLoop):
        self._shutdown_signal_received_count += 1
        if self._shutdown_signal_received_count > 1:
            self._logger.info(
                (
                    f"Received exit signal {sig.name}. Not processing as"
                    " shutdown sequence was already initiated..."
                ),
            )
        else:
            self._logger.info(
                (
                    f"Received exit signal {sig.name}. Processing shutdown"
                    " sequence..."
                ),
            )
            # check the done or cancelled status of self._running_callback_tasks.values()
            for u_uid, t in self._running_callback_tasks.items():
                self._logger.debug(
                    (
                        "Shutdown handler: Checking result and status of"
                        " aio_pika consumer callback task {}"
                    ),
                    t.get_name(),
                )
                try:
                    task_result = t.result()
                except asyncio.CancelledError:
                    self._logger.info(
                        (
                            "Shutdown handler: aio_pika consumer callback task"
                            " {} was cancelled"
                        ),
                        t.get_name(),
                    )
                except asyncio.InvalidStateError:
                    self._logger.info(
                        (
                            "Shutdown handler: aio_pika consumer callback task"
                            " {} result not available yet. Still running."
                        ),
                        t.get_name(),
                    )
                except Exception as e:
                    self._logger.info(
                        (
                            "Shutdown handler: aio_pika consumer callback task"
                            " {} raised Exception. {}"
                        ),
                        t.get_name(),
                        e,
                    )
                else:
                    self._logger.info(
                        (
                            "Shutdown handler: aio_pika consumer callback task"
                            " returned with result {}"
                        ),
                        t.get_name(),
                        task_result,
                    )

            tasks = [
                t
                for t in asyncio.all_tasks(loop)
                if t is not asyncio.current_task(loop)
            ]

            [task.cancel() for task in tasks]

            self._logger.info(f"Cancelling {len(tasks)} outstanding tasks")
            await asyncio.gather(*tasks, return_exceptions=True)
            loop.stop()
            self._logger.info("Shutdown complete.")

    async def _rabbitmq_consumer(self, loop):
        self._rmq_connection_pool = Pool(get_rabbitmq_connection, max_size=5, loop=loop)
        self._rmq_channel_pool = Pool(
            partial(get_rabbitmq_channel, self._rmq_connection_pool),
            max_size=20,
            loop=loop,
        )
        async with self._rmq_channel_pool.acquire() as channel:
            await channel.set_qos(20)
            exchange = await channel.get_exchange(
                name=self._exchange_name,
            )
            q_obj = await channel.get_queue(
                name=self._q,
                ensure=False,
            )
            self._logger.debug(
                f"Consuming queue {self._q} with routing key {self._rmq_routing}...",
            )
            await q_obj.bind(exchange, routing_key=self._rmq_routing)
            await q_obj.consume(self._on_rabbitmq_message)

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        pass

    async def _init_redis_pool(self):
        if self._aioredis_pool is not None:
            return
        self._aioredis_pool = RedisPoolCache()
        await self._aioredis_pool.populate()
        self._redis_conn = self._aioredis_pool._aioredis_pool

    async def _init_rpc_helper(self):
        if self._rpc_helper is None:
            self._rpc_helper = RpcHelper()

        if self._anchor_rpc_helper is None:
            self._anchor_rpc_helper = RpcHelper(rpc_settings=settings.anchor_chain_rpc)

            self.protocol_state_contract = self._anchor_rpc_helper.get_current_node()[
                "web3_client"
            ].eth.contract(
                address=Web3.toChecksumAddress(
                    self.protocol_state_contract_address,
                ),
                abi=self.protocol_state_contract_abi,
            )

    async def _init_httpx_client(self):
        if self._async_transport is not None:
            return
        self._async_transport = AsyncHTTPTransport(
            limits=Limits(
                max_connections=100,
                max_keepalive_connections=50,
                keepalive_expiry=None,
            ),
        )
        self._client = AsyncClient(
            timeout=Timeout(timeout=5.0),
            follow_redirects=False,
            transport=self._async_transport,
        )

    def run(self) -> None:
        setproctitle(self._unique_id)
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (settings.rlimit.file_descriptors, hard),
        )
        ev_loop = asyncio.get_event_loop()
        signals = (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT)
        for s in signals:
            ev_loop.add_signal_handler(
                s,
                lambda x=s: ev_loop.create_task(
                    self._shutdown_handler(x, ev_loop),
                ),
            )
        self._logger.debug(
            f"Starting asynchronous callback worker {self._unique_id}...",
        )
        self._core_rmq_consumer = asyncio.ensure_future(
            self._rabbitmq_consumer(ev_loop),
        )
        try:
            ev_loop.run_forever()
        finally:
            ev_loop.close()
