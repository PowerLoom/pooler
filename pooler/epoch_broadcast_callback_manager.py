import json
import os
import signal
import time
from multiprocessing import Process
from signal import SIGINT
from signal import SIGQUIT
from signal import SIGTERM

import redis
from setproctitle import setproctitle

from pooler.settings.config import projects
from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.rabbitmq_helpers import RabbitmqSelectLoopInteractor
from pooler.utils.redis.redis_conn import create_redis_conn
from pooler.utils.redis.redis_conn import REDIS_CONN_CONF
from pooler.utils.redis.redis_keys import powerloom_broadcast_id_zset
from pooler.utils.redis.redis_keys import uniswap_cb_broadcast_processing_logs_zset


def append_epoch_context(msg_json: dict):
    injected_contract = os.getenv('EPOCH_CONTEXT_INJECT')
    if injected_contract:
        msg_json['contracts'] = [injected_contract.lower()]
        return
    contracts = [project.contract for project in projects if project.enabled]
    msg_json['contracts'] = contracts


class EpochCallbackManager(Process):
    def __init__(self, name, **kwargs):
        Process.__init__(self, name=name, **kwargs)
        callback_q_conf_path = f'{settings.rabbitmq.setup.callbacks.path}{settings.rabbitmq.setup.callbacks.config}'
        with open(callback_q_conf_path, 'r') as f:
            # TODO: code the callback modules rabbitmq queue setup into pydantic model
            self._callback_q_config = json.load(f)
        self.rabbitmq_interactor = None
        self._shutdown_initiated = False
        self._project_actions = set([project.action for project in projects])

    # TODO: to make a tryly async consumer, define the work bit in here and let it run as a thread
    #       use self._rmq_callback_threads to monitor, join and clean up launched 'works'

    def _epoch_broadcast_callback_work(self):
        pass

    def _epoch_broadcast_callback(self, dont_use_ch, method, properties, body):
        broadcast_json = json.loads(body)
        self._logger.debug('Got epoch broadcast: {}', broadcast_json)
        append_epoch_context(broadcast_json)

        callback_exchange_name = f'{settings.rabbitmq.setup.callbacks.exchange}:{settings.namespace}'
        with create_redis_conn(self._connection_pool) as r:
            for topic in self._callback_q_config['callback_topics'].keys():
                # send epoch context to third party worker modules as registered
                routing_key = f'powerloom-backend-callback:{settings.namespace}:{settings.instance_id}.{topic}'
                self.rabbitmq_interactor.enqueue_msg_delivery(
                    exchange=callback_exchange_name,
                    routing_key=routing_key,
                    msg_body=json.dumps(broadcast_json),
                )
                self._logger.debug(f'Sent epoch to callback routing key {routing_key}: {body}')
                update_log = {
                    'worker': 'EpochCallbackManager',
                    'update': {
                        'action': 'CallbackQueue.Publish',
                        'info': {
                            'routing_key': routing_key,
                            'exchange': callback_exchange_name,
                            'msg': broadcast_json,
                        },
                    },
                }
                r.zadd(
                    uniswap_cb_broadcast_processing_logs_zset.format(
                        broadcast_json['broadcast_id'],
                    ),
                    {json.dumps(update_log): int(time.time())},
                )

            r.zadd(
                powerloom_broadcast_id_zset, {
                    broadcast_json['broadcast_id']: int(time.time()),
                },
            )
            # attempt to keep broadcast id processing logs set at 20
            to_be_pruned_ts = settings.epoch.height * settings.epoch.block_time * 20
            older_broadcast_ids = r.zrangebyscore(
                powerloom_broadcast_id_zset, min='-inf', max=int(time.time() - to_be_pruned_ts), withscores=False,
            )
            if older_broadcast_ids:
                older_broadcast_ids_dec = map(lambda x: x.decode('utf-8'), older_broadcast_ids)
                [
                    r.delete(uniswap_cb_broadcast_processing_logs_zset.format(k))
                    for k in older_broadcast_ids_dec
                ]
            r.zremrangebyscore(
                powerloom_broadcast_id_zset, min='-inf',
                max=int(time.time() - to_be_pruned_ts),
            )
        self.rabbitmq_interactor._channel.basic_ack(delivery_tag=method.delivery_tag)

    def _exit_signal_handler(self, signum, sigframe):
        if signum in [SIGINT, SIGTERM, SIGQUIT] and not self._shutdown_initiated:
            self._shutdown_initiated = True
            self.rabbitmq_interactor.stop()

    def run(self) -> None:
        # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|EpochCallbackManager'))
        for signame in [SIGINT, SIGTERM, SIGQUIT]:
            signal.signal(signame, self._exit_signal_handler)
        setproctitle(
            f'PowerLoom|EpochCallbackManager:{settings.namespace}-{settings.instance_id[:5]}',
        )
        self._logger = logger.bind(
            module=f'PowerLoom|EpochCallbackManager:{settings.namespace}-{settings.instance_id}',
        )

        self._logger.debug('Launched PowerLoom|EpochCallbackManager with PID: {}', self.pid)
        self._connection_pool = redis.BlockingConnectionPool(**REDIS_CONN_CONF)
        queue_name = f'powerloom-epoch-broadcast-q:{settings.namespace}:{settings.instance_id}'
        self.rabbitmq_interactor: RabbitmqSelectLoopInteractor = RabbitmqSelectLoopInteractor(
            consume_queue_name=queue_name,
            consume_callback=self._epoch_broadcast_callback,
        )
        # self.rabbitmq_interactor.start_publishing()
        self._logger.debug('Starting RabbitMQ consumer on queue {}', queue_name)
        self.rabbitmq_interactor.run()
