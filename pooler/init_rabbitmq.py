import aio_pika
import pika

from pooler.settings.config import projects_config
from pooler.settings.config import settings
from pooler.utils.default_logger import logger

# setup logging
init_rmq_logger = logger.bind(module='PowerLoom|RabbitMQ|Init')


def create_rabbitmq_conn() -> pika.BlockingConnection:
    c = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=settings.rabbitmq.host,
            port=settings.rabbitmq.port,
            virtual_host='/',
            credentials=pika.PlainCredentials(
                username=settings.rabbitmq.user,
                password=settings.rabbitmq.password,
            ),
            heartbeat=30,
        ),
    )
    return c


async def get_rabbitmq_connection_async() -> aio_pika.Connection:
    return await aio_pika.connect_robust(
        host=settings.rabbitmq.host,
        port=settings.rabbitmq.port,
        virtual_host='/',
        login=settings.rabbitmq.user,
        password=settings.rabbitmq.password,
    )


def processhub_command_publish(ch: pika.adapters.blocking_connection.BlockingChannel, cmd: str) -> None:
    ch.basic_publish(
        exchange=f'{settings.rabbitmq.setup.core.exchange}:{settings.namespace}',
        routing_key=f'processhub-commands:{settings.namespace}:{settings.instance_id}',
        body=cmd.encode('utf-8'),
        properties=pika.BasicProperties(
            delivery_mode=2,
            content_type='text/plain',
            content_encoding='utf-8',
        ),
        mandatory=True,
    )


def init_callback_queue(ch: pika.adapters.blocking_connection.BlockingChannel) -> None:
    callback_exchange_name = f'{settings.rabbitmq.setup.callbacks.exchange}:{settings.namespace}'
    # exchange declaration for top level callback modules to listen in on
    ch.exchange_declare(exchange=callback_exchange_name, exchange_type='topic', durable=True)
    init_rmq_logger.debug(
        'Initialized RabbitMQ Topic exchange for top level callbacks: {}', callback_exchange_name,
    )
    # for example, callbacks for trade volume calculation may be sent on routing key
    # 'powerloom-backend-callback:{settings.namespace}.trade_volume'
    routing_key_pattern = f'powerloom-backend-callback:{settings.namespace}:{settings.instance_id}.*'
    queue_name = f'powerloom-backend-cb:{settings.namespace}:{settings.instance_id}'
    init_queue(
        ch, queue_name=queue_name, routing_key=routing_key_pattern,
        exchange_name=callback_exchange_name,
    )
    # for internal worker distribution by top level callback modules
    project_types = set([project_config.project_type for project_config in projects_config])

    workers_exchange_name = f'{settings.rabbitmq.setup.callbacks.exchange}.workers:{settings.namespace}'
    ch.exchange_declare(exchange=workers_exchange_name, exchange_type='direct', durable=True)

    for type_ in project_types:
        topic_routing_key = f'powerloom-backend-callback:{settings.namespace}:{settings.instance_id}.{type_}_worker'
        queue_name = f'powerloom-backend-cb-{type_}:{settings.namespace}:{settings.instance_id}'
        init_queue(ch, queue_name, topic_routing_key, workers_exchange_name)


def init_queue(ch: pika.adapters.blocking_connection.BlockingChannel, queue_name: str, routing_key: str, exchange_name: str) -> None:
    ch.queue_declare(queue_name)
    ch.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=routing_key)
    init_rmq_logger.debug(
        'Initialized RabbitMQ setup | Queue: {} | Exchange: {} | Routing Key: {}',
        queue_name,
        exchange_name,
        routing_key,
    )


def init_exchanges_queues():
    c = create_rabbitmq_conn()
    ch: pika.adapters.blocking_connection.BlockingChannel = c.channel()
    # core exchange remains same for multiple pooler instances in the namespace to share across different instance IDs
    exchange_name = f'{settings.rabbitmq.setup.core.exchange}:{settings.namespace}'
    ch.exchange_declare(exchange=exchange_name, exchange_type='direct', durable=True)
    init_rmq_logger.debug('Initialized RabbitMQ Direct exchange: {}', exchange_name)

    to_be_inited = [
        ('powerloom-processhub-commands-q', 'processhub-commands'),
        (
            'powerloom-epoch-broadcast-q',
            'epoch-broadcast',
        ), ('powerloom-epoch-confirm-cb-q', 'epoch-confirm-cb'),
    ]
    for queue_name, routing_key in to_be_inited:
        # add namespace and instance ID to facilitate multiple pooler instances sharing same rabbitmq setup and broker
        q = f'{queue_name}:{settings.namespace}:{settings.instance_id}'
        r = f'{routing_key}:{settings.namespace}:{settings.instance_id}'
        init_queue(ch, q, r, exchange_name)

    init_callback_queue(ch)


if __name__ == '__main__':
    init_exchanges_queues()
