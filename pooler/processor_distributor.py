import asyncio
import json
import multiprocessing
import queue
import time
from functools import partial
from typing import Union
from uuid import uuid4

from aio_pika import IncomingMessage
from aio_pika import Message
from aio_pika.pool import Pool
from eth_utils import keccak
from pydantic import ValidationError
from setproctitle import setproctitle
from web3 import Web3

from pooler.settings.config import aggregator_config
from pooler.settings.config import projects_config
from pooler.settings.config import settings
from pooler.utils.callback_helpers import get_rabbitmq_channel
from pooler.utils.callback_helpers import get_rabbitmq_connection
from pooler.utils.data_utils import get_source_chain_epoch_size
from pooler.utils.data_utils import get_source_chain_id
from pooler.utils.default_logger import logger
from pooler.utils.models.message_models import EpochBroadcast
from pooler.utils.models.message_models import PayloadCommitFinalizedMessage
from pooler.utils.models.message_models import PowerloomCalculateAggregateMessage
from pooler.utils.models.message_models import PowerloomSnapshotFinalizedMessage
from pooler.utils.models.message_models import PowerloomSnapshotProcessMessage
from pooler.utils.models.settings_model import AggregateOn
from pooler.utils.redis.redis_conn import RedisPoolCache
from pooler.utils.redis.redis_keys import project_finalized_data_zset
from pooler.utils.rpc import RpcHelper
from pooler.utils.snapshot_utils import warm_up_cache_for_snapshot_constructors


class ProcessorDistributor(multiprocessing.Process):
    def __init__(self, name, **kwargs):
        super(ProcessorDistributor, self).__init__(name=name, **kwargs)
        self._unique_id = f'{name}-' + keccak(text=str(uuid4())).hex()[:8]
        self._q = queue.Queue()
        self._rabbitmq_interactor = None
        self._shutdown_initiated = False
        self._redis_conn = None
        self._aioredis_pool = None
        self._rpc_helper = None
        self._source_chain_id = None
        self._consume_exchange_name = f'{settings.rabbitmq.setup.event_detector.exchange}:{settings.namespace}'
        self._consume_queue_name = (
            f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}'
        )
        self._initialized = False
        self._consume_queue_routing_key = f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}.*'
        self._callback_exchange_name = (
            f'{settings.rabbitmq.setup.callbacks.exchange}:{settings.namespace}'
        )
        self._payload_commit_exchange_name = (
            f'{settings.rabbitmq.setup.commit_payload.exchange}:{settings.namespace}'
        )
        self._payload_commit_routing_key = f'powerloom-backend-commit-payload:{settings.namespace}:{settings.instance_id}.Finalized'

    async def _init_redis_pool(self):
        if not self._aioredis_pool:
            self._aioredis_pool = RedisPoolCache()
            await self._aioredis_pool.populate()
            self._redis_conn = self._aioredis_pool._aioredis_pool

    async def _init_rpc_helper(self):
        if not self._rpc_helper:
            self._rpc_helper = RpcHelper()
            self._anchor_rpc_helper = RpcHelper(rpc_settings=settings.anchor_chain_rpc)
            with open(settings.protocol_state.abi, 'r') as f:
                abi_dict = json.load(f)
            protocol_state_contract = self._anchor_rpc_helper.get_current_node()['web3_client'].eth.contract(
                address=Web3.toChecksumAddress(
                    settings.protocol_state.address,
                ),
                abi=abi_dict,
            )
            await get_source_chain_epoch_size(
                redis_conn=self._redis_conn,
                rpc_helper=self._anchor_rpc_helper,
                state_contract_obj=protocol_state_contract,
            )
            self._source_chain_id = await get_source_chain_id(
                redis_conn=self._redis_conn,
                rpc_helper=self._anchor_rpc_helper,
                state_contract_obj=protocol_state_contract,
            )

    async def _warm_up_cache_for_epoch_data(
        self, msg_obj: PowerloomSnapshotProcessMessage,
    ):
        """
        Function to warm up the cache which is used across all snapshot constructors
        and/or for internal helper functions.
        """

        try:
            max_chain_height = msg_obj.end
            min_chain_height = msg_obj.begin
            await warm_up_cache_for_snapshot_constructors(
                from_block=min_chain_height,
                to_block=max_chain_height,
                redis_conn=self._redis_conn,
                rpc_helper=self._rpc_helper,
            )

        except Exception as exc:
            self._logger.warning(
                (
                    'There was an error while warming-up cache for epoch data.'
                    f' error_msg: {exc}'
                ),
            )

    async def _publish_message_to_queue(
        self,
        exchange,
        routing_key,
        message: Union[EpochBroadcast, PowerloomCalculateAggregateMessage, PowerloomSnapshotFinalizedMessage],
    ):
        """
        Publishes a message to a rabbitmq queue
        """
        try:
            async with self._rmq_connection_pool.acquire() as connection:
                async with self._rmq_channel_pool.acquire() as channel:
                    # Prepare a message to send
                    exchange = await channel.get_exchange(
                        name=exchange,
                    )
                    message_data = message.json().encode()

                    # Prepare a message to send
                    queue_message = Message(message_data)

                    await exchange.publish(
                        message=queue_message,
                        routing_key=routing_key,
                    )

                    self._logger.info(
                        'Sent message to queue: {}', message,
                    )

        except Exception as e:
            self._logger.opt(exception=True).error(
                (
                    'Exception sending message to queue. '
                    ' {} | dump: {}'
                ),
                message,
                e,
            )

    async def _distribute_callbacks_snapshotting(self, message: IncomingMessage):
        try:
            msg_obj: EpochBroadcast = (
                EpochBroadcast.parse_raw(message.body)
            )
        except ValidationError:
            self._logger.opt(exception=True).error(
                'Bad message structure of epoch callback',
            )
            return
        except Exception:
            self._logger.opt(exception=True).error(
                'Unexpected message format of epoch callback',
            )
            return
        self._logger.debug(f'Epoch Distribution time - {int(time.time())}')
        # warm-up cache before constructing snapshots
        await self._warm_up_cache_for_epoch_data(msg_obj=msg_obj)

        for project_config in projects_config:
            type_ = project_config.project_type
            for project in project_config.projects:
                contract = project.lower()
                process_unit = PowerloomSnapshotProcessMessage(
                    begin=msg_obj.begin,
                    end=msg_obj.end,
                    epochId=msg_obj.epochId,
                    contract=contract,
                    broadcastId=msg_obj.broadcastId,
                )

                await self._publish_message_to_queue(
                    exchange=self._callback_exchange_name,
                    routing_key=f'powerloom-backend-callback:{settings.namespace}:{settings.instance_id}:EpochReleased.{type_}',
                    message=process_unit,
                )

                self._logger.debug(
                    'Sent out message to be processed by worker'
                    f' {type_} : {process_unit}',
                )

    async def _cache_and_forward_to_payload_commit_queue(self, message: IncomingMessage):
        event_type = message.routing_key.split('.')[-1]

        if event_type == 'SnapshotFinalized':
            msg_obj: PowerloomSnapshotFinalizedMessage = (
                PowerloomSnapshotFinalizedMessage.parse_raw(message.body)
            )
        else:
            return

        # Add to project finalized data zset
        await self._redis_conn.zadd(
            project_finalized_data_zset(project_id=msg_obj.projectId),
            {msg_obj.snapshotCid: msg_obj.epochId},
        )

        # TODO: prune zset

        self._logger.debug(f'Payload Commit Message Distribution time - {int(time.time())}')

        process_unit = PayloadCommitFinalizedMessage(
            message=msg_obj,
            web3Storage=True,
            sourceChainId=self._source_chain_id,
        )

        await self._publish_message_to_queue(
            exchange=self._payload_commit_exchange_name,
            routing_key=self._payload_commit_routing_key,
            message=process_unit,
        )

        self._logger.debug(
            (
                'Sent out Event to Payload Commit Queue'
                f' {event_type} : {process_unit}'
            ),
        )

    async def _distribute_callbacks_aggregate(self, message: IncomingMessage):
        event_type = message.routing_key.split('.')[-1]
        try:
            if event_type != 'SnapshotFinalized':
                self._logger.error(f'Unknown event type {event_type}')
                return

            process_unit: PowerloomSnapshotFinalizedMessage = (
                PowerloomSnapshotFinalizedMessage.parse_raw(message.body)
            )

        except ValidationError:
            self._logger.opt(exception=True).error(
                'Bad message structure of event callback',
            )
            return
        except Exception:
            self._logger.opt(exception=True).error(
                'Unexpected message format of event callback',
            )
            return
        self._logger.debug(f'Aggregation Task Distribution time - {int(time.time())}')

        # go through aggregator config, if it matches then send appropriate message
        for config in aggregator_config:
            type_ = config.project_type

            if config.aggregate_on == AggregateOn.single_project:
                if config.filters.projectId not in process_unit.projectId:
                    self._logger.info(f'projectId mismatch {process_unit.projectId} {config.filters.projectId}')
                    continue
                await self._publish_message_to_queue(
                    exchange=self._callback_exchange_name,
                    routing_key=f'powerloom-backend-callback:{settings.namespace}:'
                    f'{settings.instance_id}:CalculateAggregate.{type_}',
                    message=process_unit,
                )
            elif config.aggregate_on == AggregateOn.multi_project:
                if process_unit.projectId not in config.projects_to_wait_for:
                    self._logger.info(f'projectId not required for {config.project_type}: {process_unit.projectId}')
                    continue

                await self._redis_conn.zadd(
                    f'powerloom:aggregator:{config.project_type}:events',
                    {process_unit.json(): process_unit.epochId},
                )

                events = await self._redis_conn.zrangebyscore(
                    f'powerloom:aggregator:{config.project_type}:events',
                    process_unit.epochId,
                    process_unit.epochId,
                )

                if not events:
                    self._logger.info(f'No events found for {process_unit.epochId}')
                    continue

                event_project_ids = set()
                finalized_messages = list()

                for event in events:
                    event = PowerloomSnapshotFinalizedMessage.parse_raw(event)
                    event_project_ids.add(event.projectId)
                    finalized_messages.append(event)

                if event_project_ids == set(config.projects_to_wait_for):
                    self._logger.info(f'All projects present for {process_unit.epochId}, aggregating')
                    final_msg = PowerloomCalculateAggregateMessage(
                        messages=finalized_messages,
                        epochId=process_unit.epochId,
                        timestamp=int(time.time()),
                        broadcastId=str(uuid4()),
                    )

                    await self._publish_message_to_queue(
                        exchange=self._callback_exchange_name,
                        routing_key=f'powerloom-backend-callback:{settings.namespace}'
                        f':{settings.instance_id}:CalculateAggregate.{type_}',
                        message=final_msg,
                    )

                    # Cleanup redis
                    await self._redis_conn.zremrangebyscore(
                        f'powerloom:aggregator:{config.project_type}:events',
                        process_unit.epochId,
                        process_unit.epochId,
                    )

                else:
                    self._logger.info(
                        f'Not all projects present for {process_unit.epochId},'
                        f' {len(set(config.projects_to_wait_for)) - len(event_project_ids)} missing',
                    )

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        message_type = message.routing_key.split('.')[-1]
        self._logger.debug(
            (
                'Got message to process and distribute: {}'
            ),
            message.body,
        )

        if not self._initialized:
            await self._init_redis_pool()
            await self._init_rpc_helper()
            self._initialized = True

        if message_type == 'EpochReleased':
            await self._distribute_callbacks_snapshotting(
                message,
            )

        elif message_type == 'SnapshotFinalized':
            await self._distribute_callbacks_aggregate(
                message,
            )

            await self._cache_and_forward_to_payload_commit_queue(message),

        else:
            self._logger.error(
                (
                    'Unknown routing key for callback distribution: {}'
                ),
                message.routing_key,
            )

        await message.ack()

    async def _rabbitmq_consumer(self, loop):
        self._rmq_connection_pool = Pool(get_rabbitmq_connection, max_size=5, loop=loop)
        self._rmq_channel_pool = Pool(
            partial(get_rabbitmq_channel, self._rmq_connection_pool), max_size=20,
            loop=loop,
        )
        async with self._rmq_channel_pool.acquire() as channel:
            await channel.set_qos(20)
            exchange = await channel.get_exchange(
                name=self._consume_exchange_name,
            )
            q_obj = await channel.get_queue(
                name=self._consume_queue_name,
                ensure=False,
            )
            self._logger.debug(
                f'Consuming queue {self._consume_queue_name} with routing key {self._consume_queue_routing_key}...',
            )
            await q_obj.bind(exchange, routing_key=self._consume_queue_routing_key)
            await q_obj.consume(self._on_rabbitmq_message)

    def run(self) -> None:
        setproctitle(self.name)

        self._logger = logger.bind(
            module=f'PowerLoom|Callbacks|ProcessDistributor:{settings.namespace}-{settings.instance_id}',
        )

        ev_loop = asyncio.get_event_loop()
        self._logger.debug('Starting RabbitMQ consumer on queue {} for Processor Distributor', self._consume_queue_name)
        self._core_rmq_consumer = asyncio.ensure_future(
            self._rabbitmq_consumer(ev_loop),
        )
        try:
            ev_loop.run_forever()
        finally:
            ev_loop.close()
