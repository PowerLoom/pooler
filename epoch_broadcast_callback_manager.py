import pika
from init_rabbitmq import create_rabbitmq_conn
from rabbitmq_helpers import RabbitmqSelectLoopInteractor
from redis_keys import powerloom_broadcast_id_zset
from redis_conn import create_redis_conn, REDIS_CONN_CONF
from dynaconf import settings
from multiprocessing import Process
import threading
import redis
import time
import logging
import logging.handlers
import sys
import json
import os


def append_epoch_context(msg_json: dict):
    injected_contract = os.getenv('EPOCH_CONTEXT_INJECT')
    if injected_contract:
        msg_json['contracts'] = [injected_contract.lower()]
        return
    contracts = list()
    if os.path.exists('static/cached_pair_addresses.json'):
        with open('static/cached_pair_addresses.json', 'r') as fp:
            # the file contains an array of pair contract addresses
            contracts = json.load(fp)
    msg_json['contracts'] = contracts


class EpochCallbackManager(Process):
    def __init__(self, name, **kwargs):
        Process.__init__(self, name=name, **kwargs)
        callback_q_conf_path = f'{settings.RABBITMQ.SETUP.CALLBACKS.PATH}{settings.RABBITMQ.SETUP.CALLBACKS.CONFIG}'
        with open(callback_q_conf_path, 'r') as f:
            # TODO: code the callback modules rabbitmq queue setup into pydantic model
            self._callback_q_config = json.load(f)
        self._rmq_callback_threads = list()
        self.rabbitmq_interactor = None

    # TODO: to make a tryly async consumer, define the work bit in here and let it run as a thread
    #       use self._rmq_callback_threads to monitor, join and clean up launched 'works'
    def _epoch_broadcast_callback_work(self):
        pass

    def _epoch_broadcast_callback(self, dont_use_ch, method, properties, body):
        self.rabbitmq_interactor._channel.basic_ack(delivery_tag=method.delivery_tag)
        broadcast_json = json.loads(body)
        self._logger.debug('Got epoch broadcast: %s', broadcast_json)
        append_epoch_context(broadcast_json)
        with create_redis_conn(self._connection_pool) as r:
            r.zadd(powerloom_broadcast_id_zset, {body: int(time.time())})
            # remove entries older than 300 seconds
            r.zremrangebyscore(powerloom_broadcast_id_zset, min='-inf', max=int(time.time() - 300))
        callback_exchange_name = f'{settings.RABBITMQ.SETUP.CALLBACKS.EXCHANGE}:{settings.NAMESPACE}'
        for topic in self._callback_q_config['callback_topics'].keys():
            # send epoch context to third party worker modules as registered
            routing_key = f'powerloom-backend-callback:{settings.NAMESPACE}.{topic}'
            self.rabbitmq_interactor.enqueue_msg_delivery(
                exchange=callback_exchange_name,
                routing_key=f'powerloom-backend-callback:{settings.NAMESPACE}.{topic}',
                msg_body=json.dumps(broadcast_json)
            )
            self._logger.debug(f'Sent epoch to callback routing key {routing_key}: {body}')
        # send commands to actors to start processing this pronto
        # trade_vol_proc_actor = self._asys.createActor(
        #     'callback_modules.trade_volume.TradeVolumeProcessorDistributor',
        #     globalName='powerloom:polymarket:TradeVolumeProcessorDistributor'
        # )
        # self._asys.tell(trade_vol_proc_actor, broadcast_json)
        # self._logger.debug('Triggered call to TradeVolumeProcessorDistributor Actor')

    def run(self) -> None:
        # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|EpochCallbackManager'))
        self._logger = logging.getLogger('PowerLoom|EpochCallbackManager')
        self._logger.setLevel(logging.DEBUG)
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(logging.DEBUG)
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.ERROR)
        self._logger.handlers = [
            logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT),
            stdout_handler,
            stderr_handler
        ]
        self._logger.debug('Launched PowerLoom|EpochCallbackManager with PID: %s', self.pid)
        # self._asys = ActorSystem('multiprocTCPBase', logDefs=logcfg_thespian_main)
        self._connection_pool = redis.BlockingConnectionPool(**REDIS_CONN_CONF)
        queue_name = f"powerloom-epoch-broadcast-q:{settings.NAMESPACE}"
        self.rabbitmq_interactor: RabbitmqSelectLoopInteractor = RabbitmqSelectLoopInteractor(
            consume_queue_name=queue_name,
            consume_callback=self._epoch_broadcast_callback
        )
        # self.rabbitmq_interactor.start_publishing()
        self._logger.debug('Starting RabbitMQ consumer on queue %s', queue_name)
        self.rabbitmq_interactor.run()
