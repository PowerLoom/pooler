import asyncio
import json
import multiprocessing
import queue
import signal
import time
from signal import SIGINT
from signal import SIGQUIT
from signal import SIGTERM
from uuid import uuid4

from eth_utils import keccak
from pydantic import ValidationError
from setproctitle import setproctitle

from pooler.settings.config import aggregator_config
from pooler.settings.config import indexer_config
from pooler.settings.config import projects_config
from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.models.message_models import PayloadCommitFinalizedMessage
from pooler.utils.models.message_models import PayloadCommitFinalizedMessageType
from pooler.utils.models.message_models import PowerloomAggregateFinalizedMessage
from pooler.utils.models.message_models import PowerloomIndexFinalizedMessage
from pooler.utils.models.message_models import PowerloomSnapshotFinalizedMessage
from pooler.utils.models.message_models import PowerloomSnapshotProcessMessage
from pooler.utils.models.message_models import SystemEpochStatusReport
from pooler.utils.rabbitmq_helpers import RabbitmqSelectLoopInteractor
from pooler.utils.redis.redis_conn import RedisPoolCache
from pooler.utils.redis.redis_keys import (
    cb_broadcast_processing_logs_zset,
)
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

    async def _init_redis_pool(self):
        if not self._aioredis_pool:
            self._aioredis_pool = RedisPoolCache()
            await self._aioredis_pool.populate()
            self._redis_conn = self._aioredis_pool._aioredis_pool

    async def _init_rpc_helper(self):
        if not self._rpc_helper:
            self._rpc_helper = RpcHelper()

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

        return None

    def _distribute_callbacks_snapshotting(self, dont_use_ch, method, properties, body):
        try:
            msg_obj: SystemEpochStatusReport = (
                SystemEpochStatusReport.parse_raw(body)
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
        self.ev_loop.run_until_complete(
            self._warm_up_cache_for_epoch_data(msg_obj=msg_obj),
        )
        for project_config in projects_config:
            type_ = project_config.project_type
            for project in project_config.projects:
                contract = project.lower()
                process_unit = PowerloomSnapshotProcessMessage(
                    begin=msg_obj.begin,
                    end=msg_obj.end,
                    contract=contract,
                    broadcastId=msg_obj.broadcastId,
                )
                self._send_message_for_processing(process_unit, type_)

        self._rabbitmq_interactor._channel.basic_ack(
            delivery_tag=method.delivery_tag,
        )

    def _distribute_callbacks_indexing(self, dont_use_ch, method, properties, body):
        try:
            process_unit: PowerloomSnapshotFinalizedMessage = (
                PowerloomSnapshotFinalizedMessage.parse_raw(body)
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
        self._logger.debug(f'Indexing Task Distribution time - {int(time.time())}')

        for config in indexer_config:
            type_ = config.project_type
            self._send_message_for_processing(process_unit, type_)

        self._rabbitmq_interactor._channel.basic_ack(
            delivery_tag=method.delivery_tag,
        )

    def _send_message_for_processing(self, process_unit, type_):
        self._rabbitmq_interactor.enqueue_msg_delivery(
            exchange=f'{settings.rabbitmq.setup.callbacks.exchange}:{settings.namespace}',
            routing_key=f'powerloom-backend-callback:{settings.namespace}:{settings.instance_id}.{type_}',
            msg_body=process_unit.json(),
        )
        self._logger.debug(
            (
                'Sent out message to be processed by worker'
                f' {type_} : {process_unit}'
            ),
        )

        update_log = {
            'worker': self.name,
            'update': {
                'action': 'RabbitMQ.Publish',
                'info': {
                    'routing_key': f'powerloom-backend-callback:{settings.namespace}'
                    f':{settings.instance_id}.{type_}',
                    'exchange': f'{settings.rabbitmq.setup.callbacks.exchange}:{settings.namespace}',
                    'msg': process_unit.dict(),
                },
            },
        }
        self.ev_loop.run_until_complete(
            self._redis_conn.zadd(
                cb_broadcast_processing_logs_zset.format(
                    process_unit.broadcastId,
                ),
                {json.dumps(update_log): int(time.time())},
            ),
        )

    def _build_and_forward_to_payload_commit_queue(self, dont_use_ch, method, properties, body):
        event_type = method.routing_key.split('.')[-1]

        if event_type == 'IndexFinalized':
            msg_obj: PowerloomIndexFinalizedMessage = (
                PowerloomIndexFinalizedMessage.parse_raw(body)
            )
            msg_type = PayloadCommitFinalizedMessageType.INDEXFINALIZED
        elif event_type == 'AggregateFinalized':
            msg_obj: PowerloomAggregateFinalizedMessage = (
                PowerloomAggregateFinalizedMessage.parse_raw(body)
            )
            msg_type = PayloadCommitFinalizedMessageType.AGGREGATEFINALIZED
        elif event_type == 'SnapshotFinalized':
            msg_obj: PowerloomSnapshotFinalizedMessage = (
                PowerloomSnapshotFinalizedMessage.parse_raw(body)
            )
            msg_type = PayloadCommitFinalizedMessageType.SNAPSHOTFINALIZED

        self._logger.debug(f'Payload Commit Message Distribution time - {int(time.time())}')

        process_unit = PayloadCommitFinalizedMessage(
            messageType=msg_type,
            message=msg_obj,
            web3Storage=True,
            sourceChainId=settings.chain_id,
        )

        exchange = (
            f'{settings.rabbitmq.setup.commit_payload.exchange}:{settings.namespace}'
        )
        routing_key = f'powerloom-backend-commit-payload:{settings.namespace}:{settings.instance_id}.Finalized'

        self._rabbitmq_interactor.enqueue_msg_delivery(
            exchange=exchange,
            routing_key=routing_key,
            msg_body=process_unit.json(),
        )
        self._logger.debug(
            (
                'Sent out Event to Payload Commit Queue'
                f' {event_type} : {process_unit}'
            ),
        )

    def _distribute_callbacks_aggregate(self, dont_use_ch, method, properties, body):
        event_type = method.routing_key.split('.')[-1]
        try:
            if event_type == 'IndexFinalized':
                process_unit: PowerloomIndexFinalizedMessage = (
                    PowerloomIndexFinalizedMessage.parse_raw(body)
                )
            elif event_type == 'AggregateFinalized':
                process_unit: PowerloomAggregateFinalizedMessage = (
                    PowerloomAggregateFinalizedMessage.parse_raw(body)
                )
            else:
                self._logger.error(f'Unknown event type {event_type}')
                return

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
            if config.init_on_event != event_type:
                continue
            type_ = config.project_type

            if event_type == 'IndexFinalized':
                if process_unit.indexIdentifierHash != config.filters.indexIdentifierHash:
                    self._logger.info(
                        f'indexIdentifierHash mismatch {process_unit.indexIdentifierHash}'
                        f' {config.filters.indexIdentifierHash}',
                    )
                    continue
                if config.filters.projectId not in process_unit.projectId:
                    self._logger.info(f'projectId mismatch {process_unit.projectId} {config.filters.projectId}')
                    continue
                self._send_message_for_processing(process_unit, type_)
            if event_type == 'AggregateFinalized':
                if process_unit.projectId not in config.projects_to_wait_for:
                    self._logger.info(f'projectId not required for  {process_unit.projectId}: {config.project_type}')
                    continue
                self._send_message_for_processing(process_unit, type_)

        self._rabbitmq_interactor._channel.basic_ack(
            delivery_tag=method.delivery_tag,
        )

    def _distribute_callbacks(self, dont_use_ch, method, properties, body):
        self._logger.debug(
            (
                'Got message to process and distribute: {}'
            ),
            body,
        )
        if not self._redis_conn:
            self.ev_loop.run_until_complete(self._init_redis_pool())

        if not self._rpc_helper:
            self.ev_loop.run_until_complete(self._init_rpc_helper())

        # Forwarding SnapshotFinalized, IndexFinalized, and AggregateFinalized Events to Payload Commit Queue

        if (
            method.routing_key ==
            f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}.SnapshotFinalized' or
            method.routing_key ==
            f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}.IndexFinalized' or
            method.routing_key ==
            f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}.AggregateFinalized'
        ):
            {
                self._build_and_forward_to_payload_commit_queue(dont_use_ch, method, properties, body),
            }

        if (
            method.routing_key ==
            f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}.EpochReleased'
        ):
            self._distribute_callbacks_snapshotting(
                dont_use_ch, method, properties, body,
            )

        elif (
            method.routing_key ==
            f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}.SnapshotFinalized'
        ):
            self._distribute_callbacks_indexing(
                dont_use_ch, method, properties, body,
            )

        elif (
            method.routing_key ==
            f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}.IndexFinalized' or
            method.routing_key ==
            f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}.AggregateFinalized'
        ):
            self._distribute_callbacks_aggregate(
                dont_use_ch, method, properties, body,
            )
        else:
            self._logger.error(
                (
                    'Unknown routing key for callback distribution: {}'
                ),
                method.routing_key,
            )

    def _exit_signal_handler(self, signum, sigframe):
        if (
            signum in [SIGINT, SIGTERM, SIGQUIT] and
            not self._shutdown_initiated
        ):
            self._shutdown_initiated = True
            self._rabbitmq_interactor.stop()

    def run(self) -> None:
        setproctitle(self.name)
        for signame in [SIGINT, SIGTERM, SIGQUIT]:
            signal.signal(signame, self._exit_signal_handler)

        self._logger = logger.bind(
            module=f'PowerLoom|Callbacks|ProcessDistributor:{settings.namespace}-{settings.instance_id}',
        )

        queue_name = (
            f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}'
        )

        self.ev_loop = asyncio.get_event_loop()
        self._rabbitmq_interactor: RabbitmqSelectLoopInteractor = RabbitmqSelectLoopInteractor(
            consume_queue_name=queue_name,
            consume_callback=self._distribute_callbacks,
            consumer_worker_name=f'PowerLoom|Callbacks|ProcessDistributor:{settings.namespace}-{settings.instance_id}',
        )
        # self.rabbitmq_interactor.start_publishing()
        self._logger.debug('Starting RabbitMQ consumer on queue {}', queue_name)
        self._rabbitmq_interactor.run()
