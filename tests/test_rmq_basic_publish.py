from init_rabbitmq import create_rabbitmq_conn
from rabbitmq_helpers import RabbitmqThreadedSelectLoopInteractor
from dynaconf import settings
import pika
import queue
import threading
import time


def interactor_wrapper_obj(q: queue.Queue):
    s = RabbitmqThreadedSelectLoopInteractor(publish_queue=q)
    s.run()


if __name__ == '__main__':
    q = queue.Queue()
    cmd = '{"command": "start", "pid": null, "proc_str_id": "EpochCallbackManager", "init_kwargs": {}}'
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
            r = ch.basic_publish(
                exchange=f'{settings.RABBITMQ.SETUP.CORE.EXCHANGE}:{settings.NAMESPACE}',
                routing_key = f'processhub-commands:{settings.NAMESPACE}',
                body=cmd.encode('utf-8'),
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type='text/plain',
                    content_encoding='utf-8'
                ),
                mandatory=True
            )
            print('Vanilla publish return value: ', r)
        else:
            print('Trying to publish via select loop adapter...')
            brodcast_msg = (cmd.encode('utf-8'), exchange, routing_key)
            q.put(brodcast_msg)
    except KeyboardInterrupt:
        t.join()
