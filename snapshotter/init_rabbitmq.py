import pika

from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import logger

# setup logging
init_rmq_logger = logger.bind(module='Powerloom|RabbitMQ|Init')


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


def processhub_command_publish(
    ch: pika.adapters.blocking_connection.BlockingChannel, cmd: str,
) -> None:
    ch.basic_publish(
        exchange=(
            f'{settings.rabbitmq.setup.core.exchange}:{settings.namespace}'
        ),
        routing_key=(
            f'processhub-commands:{settings.namespace}:{settings.instance_id}'
        ),
        body=cmd.encode('utf-8'),
        properties=pika.BasicProperties(
            delivery_mode=2,
            content_type='text/plain',
            content_encoding='utf-8',
        ),
        mandatory=True,
    )


def get_snapshot_queue_routing_key_pattern() -> tuple[str, str]:
    queue_name = (
        f'powerloom-backend-cb-snapshot:{settings.namespace}:{settings.instance_id}'
    )
    routing_key_pattern = f'powerloom-backend-callback:{settings.namespace}:{settings.instance_id}:EpochReleased.*'
    return queue_name, routing_key_pattern


def get_aggregate_queue_routing_key_pattern() -> tuple[str, str]:
    queue_name = (
        f'powerloom-backend-cb-aggregate:{settings.namespace}:{settings.instance_id}'
    )
    routing_key_pattern = f'powerloom-backend-callback:{settings.namespace}:{settings.instance_id}:CalculateAggregate.*'
    return queue_name, routing_key_pattern


def get_delegate_worker_request_queue_routing_key() -> tuple[str, str]:
    request_queue_routing_key = f'powerloom-delegated-worker:{settings.namespace}:{settings.instance_id}:Request'
    request_queue_name = f'powerloom-delegated-worker-request:{settings.namespace}:{settings.instance_id}'
    return request_queue_name, request_queue_routing_key


def get_delegate_worker_response_queue_routing_key_pattern() -> tuple[str, str]:
    response_queue_routing_key = f'powerloom-delegated-worker:{settings.namespace}:{settings.instance_id}:Response.*'
    response_queue_name = f'powerloom-delegated-worker-response:{settings.namespace}:{settings.instance_id}'
    return response_queue_name, response_queue_routing_key


def init_queue(
    ch: pika.adapters.blocking_connection.BlockingChannel,
    queue_name: str,
    routing_key: str,
    exchange_name: str,
    bind: bool = True,
) -> None:
    ch.queue_declare(queue_name)
    if bind:
        ch.queue_bind(
            exchange=exchange_name, queue=queue_name, routing_key=routing_key,
        )
    init_rmq_logger.debug(
        (
            'Initialized RabbitMQ setup | Queue: {} | Exchange: {} | Routing'
            ' Key: {}'
        ),
        queue_name,
        exchange_name,
        routing_key,
    )


def init_topic_exchange_and_queue(
    ch: pika.adapters.blocking_connection.BlockingChannel,
    exchange_name: str,
    queue_name: str,
    routing_key_pattern: str,
) -> None:
    ch.exchange_declare(
        exchange=exchange_name, exchange_type='topic', durable=True,
    )
    init_rmq_logger.debug(
        'Initialized RabbitMQ Topic exchange: {}', exchange_name,
    )
    init_queue(
        ch=ch,
        exchange_name=exchange_name,
        queue_name=queue_name,
        routing_key=routing_key_pattern,
    )


def init_callback_queue(
    ch: pika.adapters.blocking_connection.BlockingChannel,
) -> None:
    callback_exchange_name = (
        f'{settings.rabbitmq.setup.callbacks.exchange}:{settings.namespace}'
    )
    # Snapshot queue
    queue_name, routing_key_pattern = get_snapshot_queue_routing_key_pattern()
    init_topic_exchange_and_queue(
        ch,
        exchange_name=callback_exchange_name,
        queue_name=queue_name,
        routing_key_pattern=routing_key_pattern,
    )

    # Aggregate queue
    queue_name, routing_key_pattern = get_aggregate_queue_routing_key_pattern()
    init_queue(
        ch,
        exchange_name=callback_exchange_name,
        queue_name=queue_name,
        routing_key=routing_key_pattern,
    )


def init_commit_payload_queue(
    ch: pika.adapters.blocking_connection.BlockingChannel,
) -> None:
    commit_payload_exchange_name = (
        f'{settings.rabbitmq.setup.commit_payload.exchange}:{settings.namespace}'
    )
    routing_key_pattern = f'powerloom-backend-commit-payload:{settings.namespace}:{settings.instance_id}.*'
    queue_name = (
        f'powerloom-backend-commit-payload-queue:{settings.namespace}:{settings.instance_id}'
    )
    init_topic_exchange_and_queue(
        ch,
        exchange_name=commit_payload_exchange_name,
        queue_name=queue_name,
        routing_key_pattern=routing_key_pattern,
    )


def init_delegate_worker_queue(
    ch: pika.adapters.blocking_connection.BlockingChannel,
) -> None:
    delegated_worker_exchange_name = (
        f'{settings.rabbitmq.setup.delegated_worker.exchange}:{settings.namespace}'
    )

    ch.exchange_declare(
        exchange=delegated_worker_exchange_name, exchange_type='direct', durable=True,
    )

    request_queue_name, request_queue_routing_key = get_delegate_worker_request_queue_routing_key()

    init_queue(
        ch,
        exchange_name=delegated_worker_exchange_name,
        queue_name=request_queue_name,
        routing_key=request_queue_routing_key,
        bind=True,
    )


def init_event_detector_queue(
    ch: pika.adapters.blocking_connection.BlockingChannel,
) -> None:
    event_detector_exchange_name = (
        f'{settings.rabbitmq.setup.event_detector.exchange}:{settings.namespace}'
    )
    routing_key_pattern = f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}.*'
    queue_name = (
        f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}'
    )
    init_topic_exchange_and_queue(
        ch,
        exchange_name=event_detector_exchange_name,
        queue_name=queue_name,
        routing_key_pattern=routing_key_pattern,
    )


def init_exchanges_queues():
    c = create_rabbitmq_conn()
    ch: pika.adapters.blocking_connection.BlockingChannel = c.channel()
    # core exchange remains same for multiple snapshotter instances
    #  in the namespace to share across different instance IDs
    exchange_name = (
        f'{settings.rabbitmq.setup.core.exchange}:{settings.namespace}'
    )
    ch.exchange_declare(
        exchange=exchange_name, exchange_type='direct', durable=True,
    )
    init_rmq_logger.debug(
        'Initialized RabbitMQ Direct exchange: {}', exchange_name,
    )

    to_be_inited = [
        ('powerloom-processhub-commands-q', 'processhub-commands'),
    ]
    for queue_name, routing_key in to_be_inited:
        # add namespace and instance ID to facilitate multiple snapshotter instances
        #  sharing same rabbitmq setup and broker
        q = f'{queue_name}:{settings.namespace}:{settings.instance_id}'
        r = f'{routing_key}:{settings.namespace}:{settings.instance_id}'
        init_queue(ch, q, r, exchange_name)

    init_callback_queue(ch)
    init_event_detector_queue(ch)
    init_commit_payload_queue(ch)
    init_delegate_worker_queue(ch)


if __name__ == '__main__':
    init_exchanges_queues()
