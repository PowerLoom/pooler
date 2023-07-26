import asyncio
import multiprocessing
import resource
from functools import partial
from typing import Dict
from typing import Union
from uuid import uuid4

from aio_pika import IncomingMessage
from aio_pika import Message
from aio_pika.pool import Pool
from eth_utils import keccak
from httpx import AsyncClient
from httpx import AsyncHTTPTransport
from httpx import Limits
from httpx import Timeout
from pydantic import BaseModel
from redis import asyncio as aioredis
from web3 import Web3

from snapshotter.settings.config import settings
from snapshotter.utils.callback_helpers import get_rabbitmq_channel
from snapshotter.utils.callback_helpers import get_rabbitmq_robust_connection_async
from snapshotter.utils.data_utils import get_source_chain_id
from snapshotter.utils.default_logger import logger
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.models.message_models import AggregateBase
from snapshotter.utils.models.message_models import PayloadCommitMessage
from snapshotter.utils.models.message_models import PowerloomCalculateAggregateMessage
from snapshotter.utils.models.message_models import PowerloomSnapshotProcessMessage
from snapshotter.utils.models.message_models import PowerloomSnapshotSubmittedMessage
from snapshotter.utils.redis.redis_conn import RedisPoolCache
from snapshotter.utils.rpc import RpcHelper


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
        self._exchange_name = f'{settings.rabbitmq.setup.callbacks.exchange}:{settings.namespace}'
        self._unique_id = f'{name}-' + keccak(text=str(uuid4())).hex()[:8]
        self._redis_conn: Union[None, aioredis.Redis] = None
        self._running_callback_tasks: Dict[str, asyncio.Task] = dict()
        super(GenericAsyncWorker, self).__init__(name=name, **kwargs)
        self._logger = logger.bind(module=self.name)
        self._aioredis_pool = None
        self._async_transport = None
        self._rpc_helper = None
        self._anchor_rpc_helper = None
        self.protocol_state_contract = None
        self._qos = 20

        self._rate_limiting_lua_scripts = None

        self.protocol_state_contract_abi = read_json_file(
            settings.protocol_state.abi,
            self._logger,
        )
        self.protocol_state_contract_address = settings.protocol_state.address
        self._commit_payload_exchange = (
            f'{settings.rabbitmq.setup.commit_payload.exchange}:{settings.namespace}'
        )
        self._commit_payload_routing_key = (
            f'powerloom-backend-commit-payload:{settings.namespace}:{settings.instance_id}.Data'
        )
        self._initialized = False

    async def _rabbitmq_consumer(self, loop):
        self._rmq_connection_pool = Pool(get_rabbitmq_robust_connection_async, max_size=5, loop=loop)
        self._rmq_channel_pool = Pool(
            partial(get_rabbitmq_channel, self._rmq_connection_pool), max_size=20,
            loop=loop,
        )
        async with self._rmq_channel_pool.acquire() as channel:
            await channel.set_qos(self._qos)
            exchange = await channel.get_exchange(
                name=self._exchange_name,
            )
            q_obj = await channel.get_queue(
                name=self._q,
                ensure=False,
            )
            self._logger.debug(
                f'Consuming queue {self._q} with routing key {self._rmq_routing}...',
            )
            await q_obj.bind(exchange, routing_key=self._rmq_routing)
            await q_obj.consume(self._on_rabbitmq_message)

    async def _send_payload_commit_service_queue(
        self,
        type_: str,
        project_id: str,
        epoch: Union[
            PowerloomSnapshotProcessMessage,
            PowerloomSnapshotSubmittedMessage,
            PowerloomCalculateAggregateMessage,
        ],
        snapshot: Union[BaseModel, AggregateBase, None],
        storage_flag: bool,
    ):

        if not snapshot:
            self._logger.info(
                (
                    'No snapshot to commit or Construction of snapshot'
                    ' failed for {} against epoch {}'
                ),
                type_,
                epoch,
            )
        else:
            try:
                source_chain_details = await get_source_chain_id(
                    redis_conn=self._redis_conn,
                    rpc_helper=self._anchor_rpc_helper,
                    state_contract_obj=self.protocol_state_contract,
                )
            except Exception as e:
                self._logger.opt(exception=True).error(
                    'Exception getting source chain id: {}', e,
                )
                raise e
            finally:
                await self._redis_conn.close()

            payload = snapshot.dict(by_alias=True)

            commit_payload = PayloadCommitMessage(
                message=payload,
                web3Storage=storage_flag,
                sourceChainId=source_chain_details,
                projectId=project_id,
                epochId=epoch.epochId,
            )

            # send through rabbitmq
            try:
                async with self._rmq_connection_pool.acquire() as connection:
                    async with self._rmq_channel_pool.acquire() as channel:
                        # Prepare a message to send
                        commit_payload_exchange = await channel.get_exchange(
                            name=self._commit_payload_exchange,
                        )
                        message_data = commit_payload.json().encode()

                        # Prepare a message to send
                        message = Message(message_data)

                        await commit_payload_exchange.publish(
                            message=message,
                            routing_key=self._commit_payload_routing_key,
                        )

                        self._logger.info(
                            'Sent message to commit payload queue: {}', commit_payload,
                        )

            except Exception as e:
                self._logger.opt(exception=True).error(
                    (
                        'Exception committing snapshot to commit payload queue:'
                        ' {} | dump: {}'
                    ),
                    snapshot,
                    e,
                )

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
            self._rpc_helper = RpcHelper(rpc_settings=settings.rpc)

        if self._anchor_rpc_helper is None:
            self._anchor_rpc_helper = RpcHelper(rpc_settings=settings.anchor_chain_rpc)

            self.protocol_state_contract = self._anchor_rpc_helper.get_current_node()['web3_client'].eth.contract(
                address=Web3.toChecksumAddress(
                    self.protocol_state_contract_address,
                ),
                abi=self.protocol_state_contract_abi,
            )
            # cleaning up ABI
            self.protocol_state_contract_abi = None

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

    async def init(self):
        if not self._initialized:
            await self._init_redis_pool()
            await self._init_httpx_client()
            await self._init_rpc_helper()
        self._initialized = True

    def run(self) -> None:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (settings.rlimit.file_descriptors, hard),
        )
        ev_loop = asyncio.get_event_loop()
        self._logger.debug(
            f'Starting asynchronous callback worker {self._unique_id}...',
        )
        self._core_rmq_consumer = asyncio.ensure_future(
            self._rabbitmq_consumer(ev_loop),
        )
        try:
            ev_loop.run_forever()
        finally:
            ev_loop.close()
