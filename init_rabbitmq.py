from dynaconf import settings
import pika
import json
import logging
import sys
import coloredlogs
import aio_pika
from aio_pika.pool import Pool
from functools import partial


formatter = logging.Formatter(u"%(levelname)-8s %(name)-4s %(asctime)s,%(msecs)d %(module)s-%(funcName)s: %(message)s")

stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setLevel(logging.DEBUG)
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.ERROR)

init_rmq_logger = logging.getLogger(__name__)
init_rmq_logger.setLevel(logging.DEBUG)
init_rmq_logger.addHandler(stdout_handler)
init_rmq_logger.addHandler(stderr_handler)
coloredlogs.install(level='DEBUG', logger=init_rmq_logger, stream=sys.stdout)


def create_rabbitmq_conn():
    c = pika.BlockingConnection(pika.ConnectionParameters(
        host=settings.RABBITMQ.HOST,
        port=settings.RABBITMQ.PORT,
        virtual_host='/',
        credentials=pika.PlainCredentials(
            username=settings.RABBITMQ.USER,
            password=settings.RABBITMQ.PASSWORD
        ),
        heartbeat=30
    ))
    return c


async def get_rabbitmq_connection_async():
    return await aio_pika.connect_robust(
        host=settings.RABBITMQ.HOST,
        port=settings.RABBITMQ.PORT,
        virtual_host='/',
        login=settings.RABBITMQ.USER,
        password=settings.RABBITMQ.PASSWORD
    )


async def get_rabbitmq_channel_async(connection_pool) -> aio_pika.Channel:
    async with connection_pool.acquire() as connection:
        return await connection.channel()

def processhub_command_publish(ch, cmd):
    ch.basic_publish(
        exchange=f'{settings.RABBITMQ.SETUP.CORE.EXCHANGE}:{settings.NAMESPACE}',
        routing_key=f'processhub-commands:{settings.NAMESPACE}',
        body=cmd.encode('utf-8'),
        properties=pika.BasicProperties(
            delivery_mode=2,
            content_type='text/plain',
            content_encoding='utf-8'
        ),
        mandatory=True
    )


def init_callback_queue(ch: pika.adapters.blocking_connection.BlockingChannel):
    callback_q_conf_path = f'{settings.RABBITMQ.SETUP.CALLBACKS.PATH}{settings.RABBITMQ.SETUP.CALLBACKS.CONFIG}'
    with open(callback_q_conf_path, 'r') as f:
        callback_q_config = json.load(f)
    callback_exchange_name = f'{settings.RABBITMQ.SETUP.CALLBACKS.EXCHANGE}:{settings.NAMESPACE}'
    # exchange declaration for top level callback modules to listen in on
    ch.exchange_declare(exchange=callback_exchange_name, exchange_type='topic', durable=True)
    init_rmq_logger.debug('Initialized RabbitMQ Topic exchange for top level callbacks: %s', callback_exchange_name)
    # for example, callbacks for trade volume calculation may be sent on routing key
    # 'powerloom-backend-callback:{settings.NAMESPACE}.trade_volume'
    routing_key_pattern = f'powerloom-backend-callback:{settings.NAMESPACE}.*'
    queue_name = f'powerloom-backend-cb:{settings.NAMESPACE}'
    init_queue(ch, queue_name=queue_name, routing_key=routing_key_pattern, exchange_name=callback_exchange_name)
    # for internal worker distribution by top level callback modules
    sub_topic_exchange_name = f'{settings.RABBITMQ.SETUP.CALLBACKS.EXCHANGE}.subtopics:{settings.NAMESPACE}'
    ch.exchange_declare(exchange=sub_topic_exchange_name, exchange_type='direct', durable=True)
    for topic in callback_q_config['callback_topics'].keys():
        for sub_topic in callback_q_config['callback_topics'][topic]['sub_topics']:
            sub_topic_routing_key = f'powerloom-backend-callback:{settings.NAMESPACE}.{topic}_worker.{sub_topic}'
            queue_name = f'powerloom-backend-cb-{topic}-{sub_topic}:{settings.NAMESPACE}'
            init_queue(ch, queue_name, sub_topic_routing_key, sub_topic_exchange_name)


async def init_rmq_exchange_queue_async():
    rmq_connection_pool = Pool(get_rabbitmq_connection_async, max_size=5)
    rmq_channel_pool = Pool(partial(get_rabbitmq_channel_async, rmq_connection_pool), max_size=20)
    async with rmq_channel_pool.acquire() as channel:
        await channel.set_qos(10)

        #for new eth logs worker
        eth_log_exchange_name = f'{settings.RABBITMQ.SETUP.CALLBACKS.EXCHANGE}.subtopics.ethlogs:{settings.NAMESPACE}'
        eth_logs_exchange = await channel.declare_exchange(
            eth_log_exchange_name, aio_pika.ExchangeType.DIRECT
        )

        # Declaring log request receiver queue and bind to exchange
        receiverQueue_name = f'{settings.ETH_LOG_WORKER.RECEIVER_QUEUE_NAME}'
        receiverQueue = await channel.declare_queue(name=receiverQueue_name, durable=True, auto_delete=False)
        await receiverQueue.bind(eth_logs_exchange, routing_key=receiverQueue_name)

        # Declaring log result sender queue and bind to exchange
        senderQueue_name = f'{settings.ETH_LOG_WORKER.SENDER_QUEUE_NAME}'
        senderQueue = await channel.declare_queue(name=senderQueue_name, durable=True, auto_delete=False)
        await senderQueue.bind(eth_logs_exchange, routing_key=senderQueue_name)
        return eth_logs_exchange, receiverQueue, senderQueue


def init_queue(ch: pika.adapters.blocking_connection.BlockingChannel, queue_name, routing_key, exchange_name):
    ch.queue_declare(queue_name)
    ch.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=routing_key)
    init_rmq_logger.debug(
        'Initialized RabbitMQ setup | Queue: %s | Exchange: %s | Routing Key: %s',
        queue_name,
        exchange_name,
        routing_key
    )


def init_exchanges_queues():
    c = create_rabbitmq_conn()
    ch: pika.adapters.blocking_connection.BlockingChannel = c.channel()
    exchange_name = f'{settings.RABBITMQ.SETUP.CORE.EXCHANGE}:{settings.NAMESPACE}'
    ch.exchange_declare(exchange=exchange_name, exchange_type='direct', durable=True)
    init_rmq_logger.debug('Initialized RabbitMQ Direct exchange: %s', exchange_name)

    to_be_inited = [
        ('powerloom-processhub-commands-q', 'processhub-commands'), ('powerloom-epoch-consensus-q', 'epoch-consensus'),
        ('powerloom-epoch-broadcast-q', 'epoch-broadcast'), ('powerloom-epoch-confirm-cb-q', 'epoch-confirm-cb')
    ]
    for queue_name, routing_key in to_be_inited:
        # add namespace
        q = f'{queue_name}:{settings.NAMESPACE}'
        r = f'{routing_key}:{settings.NAMESPACE}'
        init_queue(ch, q, r, exchange_name)

    init_callback_queue(ch)


if __name__ == '__main__':
    init_exchanges_queues()
