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

import redis
from eth_utils import keccak
from pydantic import ValidationError
from setproctitle import setproctitle

from pooler.callback_modules.uniswap.core import (
    warm_up_cache_for_snapshot_constructors,
)
from pooler.settings.config import projects_config
from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.models.message_models import PowerloomCallbackProcessMessage
from pooler.utils.models.message_models import SystemEpochStatusReport
from pooler.utils.rabbitmq_helpers import RabbitmqSelectLoopInteractor
from pooler.utils.redis.redis_conn import create_redis_conn
from pooler.utils.redis.redis_conn import REDIS_CONN_CONF
from pooler.utils.redis.redis_keys import (
    uniswap_cb_broadcast_processing_logs_zset,
)


class ProcessorDistributor(multiprocessing.Process):
    def __init__(self, name, **kwargs):
        super(ProcessorDistributor, self).__init__(name=name, **kwargs)
        self._unique_id = f'{name}-' + keccak(text=str(uuid4())).hex()[:8]
        self._q = queue.Queue()
        self._rabbitmq_interactor = None
        self._shutdown_initiated = False

    async def _warm_up_cache_for_epoch_data(
        self, msg_obj: PowerloomCallbackProcessMessage,
    ):
        """
        Function to warm up the cache which is used across all snapshot constructors
        and/or for internal helper functions.
        """
        try:
            max_chain_height = msg_obj.end
            min_chain_height = msg_obj.begin

            await warm_up_cache_for_snapshot_constructors(
                loop=self.ev_loop,
                from_block=min_chain_height,
                to_block=max_chain_height,
            )

        except Exception as exc:
            self._logger.warning(
                (
                    'There was an error while warming-up cache for epoch data.'
                    f' error_msg: {exc}'
                ),
            )

        return None

    def _distribute_callbacks(self, dont_use_ch, method, properties, body):
        self._logger.debug(
            (
                'Got processed epoch to distribute among processors for total'
                ' reserves of a pair: {}'
            ),
            body,
        )
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

        # warm-up cache before constructing snapshots
        self.ev_loop.run_until_complete(
            self._warm_up_cache_for_epoch_data(msg_obj=msg_obj),
        )
        for project_config in projects_config:
            type_ = project_config.project_type
            for project in project_config.projects:
                contract = project.lower()
                process_unit = PowerloomCallbackProcessMessage(
                    begin=msg_obj.begin,
                    end=msg_obj.end,
                    contract=contract,
                    broadcast_id=msg_obj.broadcast_id,
                )
                self._rabbitmq_interactor.enqueue_msg_delivery(
                    exchange=f'{settings.rabbitmq.setup.callbacks.exchange}.workers:{settings.namespace}',
                    routing_key=f'powerloom-backend-callback:{settings.namespace}'
                    f':{settings.instance_id}.{type_}_worker',
                    msg_body=process_unit.json(),
                )
                self._logger.debug(
                    (
                        'Sent out epoch to be processed by worker to calculate'
                        f' total reserves for pair contract: {process_unit}'
                    ),
                )
            update_log = {
                'worker': self.name,
                'update': {
                    'action': 'RabbitMQ.Publish',
                    'info': {
                        'routing_key': f'powerloom-backend-callback:{settings.namespace}'
                        f':{settings.instance_id}.{type_}_worker',
                        'exchange': f'{settings.rabbitmq.setup.callbacks.exchange}.workers:{settings.namespace}',
                        'msg': msg_obj.dict(),
                    },
                },
            }
            with create_redis_conn(self._connection_pool) as r:
                r.zadd(
                    uniswap_cb_broadcast_processing_logs_zset.format(
                        msg_obj.broadcast_id,
                    ),
                    {json.dumps(update_log): int(time.time())},
                )
        self._rabbitmq_interactor._channel.basic_ack(
            delivery_tag=method.delivery_tag,
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

        self._connection_pool = redis.BlockingConnectionPool(**REDIS_CONN_CONF)
        queue_name = (
            f'powerloom-backend-cb:{settings.namespace}:{settings.instance_id}'
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
