import queue
import threading

import pika
from dynaconf import settings

from pooler.init_rabbitmq import create_rabbitmq_conn
from pooler.utils.rabbitmq_helpers import RabbitmqThreadedSelectLoopInteractor


def interactor_wrapper_obj(rmq_q: queue.Queue):
    rmq_interactor = RabbitmqThreadedSelectLoopInteractor(publish_queue=rmq_q)
    rmq_interactor.run()


if __name__ == '__main__':
    q = queue.Queue()
    CMD = '{"command": "start", "pid": null, "proc_str_id": "EpochCallbackManager", "init_kwargs": {}}'
    exchange = f'{settings.RABBITMQ.SETUP.CORE.EXCHANGE}:{settings.NAMESPACE}'
    routing_key = f'processhub-commands:{settings.NAMESPACE}'
    try:
        t = threading.Thread(target=interactor_wrapper_obj, kwargs={'q': q})
        t.start()
        i = input('1 for vanilla pika adapter publish. 2 for select loop adapter publish')
        i = int(i)
        if i == 1:
            c = create_rabbitmq_conn()
            ch = c.channel()
            ch.basic_publish(
                exchange=f'{settings.RABBITMQ.SETUP.CORE.EXCHANGE}:{settings.NAMESPACE}',
                routing_key = f'processhub-commands:{settings.NAMESPACE}',
                body=CMD.encode('utf-8'),
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type='text/plain',
                    content_encoding='utf-8'
                ),
                mandatory=True
            )
            print('Published to rabbitmq')
        else:
            print('Trying to publish via select loop adapter...')
            brodcast_msg = (CMD.encode('utf-8'), exchange, routing_key)
            q.put(brodcast_msg)
    except KeyboardInterrupt:
        t.join()
