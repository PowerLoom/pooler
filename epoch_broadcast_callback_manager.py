import pika
from init_rabbitmq import create_rabbitmq_conn
from redis_keys import powerloom_broadcast_id_zset
from redis_conn import create_redis_conn, REDIS_CONN_CONF
from dynaconf import settings
from multiprocessing import Process
import redis
import time
import logging
import logging.handlers
import requests
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

    def _epoch_broadcast_callback(self, ch, method, properties, body):
        ch.basic_ack(delivery_tag=method.delivery_tag)
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
            ch.basic_publish(
                exchange=callback_exchange_name,
                routing_key=f'powerloom-backend-callback:{settings.NAMESPACE}.{topic}',
                body=json.dumps(broadcast_json),
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type='text/plain',
                    content_encoding='utf-8'
                ),
                mandatory=True
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
        self._logger.handlers = [logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]
        # self._asys = ActorSystem('multiprocTCPBase', logDefs=logcfg_thespian_main)
        c = create_rabbitmq_conn()
        ch = c.channel()
        self._connection_pool = redis.BlockingConnectionPool(**REDIS_CONN_CONF)
        queue_name = f"powerloom-epoch-broadcast-q:{settings.NAMESPACE}"
        ch.basic_qos(prefetch_count=1)
        ch.basic_consume(
            queue=queue_name,
            on_message_callback=self._epoch_broadcast_callback,
            auto_ack=False
        )
        try:
            self._logger.debug('Starting RabbitMQ consumer on queue %s', queue_name)
            ch.start_consuming()
        except:
            pass
        finally:
            try:
                ch.close()
                c.close()
            except:
                pass