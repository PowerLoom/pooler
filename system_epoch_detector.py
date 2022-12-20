import redis
import sys
import signal
import threading
import logging.handlers
import queue
import time
import multiprocessing
import uuid
import requests
import json
from time import sleep
from signal import SIGINT, SIGTERM, SIGQUIT
from functools import wraps
from dynaconf import Dynaconf
from exceptions import GenericExitOnSignal
from message_models import SystemEpochStatusReport
from redis_keys import epoch_detector_last_processed_epoch
from setproctitle import setproctitle
from rabbitmq_helpers import RabbitmqThreadedSelectLoopInteractor
from redis_conn import create_redis_conn, REDIS_CONN_CONF

settings = Dynaconf(
    settings_files=["settings.json"],
    environments=True,
    load_dotenv=True,
)


def chunks(start_idx, stop_idx, n):
    """
    Yield tuples of indices representing chunks of a range.

    Arguments:
    start_idx -- the start index of the range
    stop_idx -- the stop index of the range
    chunk_size -- the size of each chunk
    """
    run_idx = 0
    for i in range(start_idx, stop_idx + 1, n):
        # Create an index range for l of n items:
        begin_idx = i  # if run_idx == 0 else i+1
        if begin_idx == stop_idx + 1:
            return
        end_idx = i + n - 1 if i + n - 1 <= stop_idx else stop_idx
        run_idx += 1
        yield begin_idx, end_idx, run_idx

def rabbitmq_and_redis_cleanup(fn):
    """
    A decorator that wraps the provided function and handles cleaning up RabbitMQ and Redis resources before exiting.
    """
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            fn(self, *args, **kwargs)
        except (GenericExitOnSignal, KeyboardInterrupt):
            try:
                self._logger.debug('Waiting for RabbitMQ interactor thread to join...')
                self._rabbitmq_thread.join()
                self._logger.debug('RabbitMQ interactor thread joined.')
                if self._last_processed_epoch:
                    self._logger.debug('Saving last processed epoch to redis...')
                    with create_redis_conn(self._connection_pool) as r:
                        r.set(epoch_detector_last_processed_epoch, json.dumps(self._last_processed_epoch))
            except Exception as E:
                self._logger.error('Error while saving progress: %s', E)
        except Exception as E:
            self._logger.error('Error while running: %s', E)
        finally:
            self._logger.debug('Shutting down!')
            sys.exit(0)
    return wrapper


class EpochDetectorProcess(multiprocessing.Process):
    def __init__(self, name, **kwargs):
        """
        Initializes a new instance of the `EpochDetectorProcess` class.
        
        Arguments:
        name -- the name of the process
        """
        multiprocessing.Process.__init__(self, name=name, **kwargs)
        self._rabbitmq_thread: threading.Thread
        self._rabbitmq_queue = queue.Queue()
        self._shutdown_initiated = False
        self._connection_pool = redis.BlockingConnectionPool(**REDIS_CONN_CONF)

        self._logger = logging.getLogger(f'{name}|{settings.NAMESPACE}-{settings.INSTANCE_ID[:5]}')
        self._logger.setLevel(logging.DEBUG)
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(logging.DEBUG)
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.ERROR)
        
        self._logger.handlers = [
            logging.handlers.SocketHandler(host=settings.get('LOGGING_SERVER.HOST','localhost'),
            port=settings.get('LOGGING_SERVER.PORT',logging.handlers.DEFAULT_TCP_LOGGING_PORT)),
            stdout_handler, 
            stderr_handler
        ]

        self.last_processed_epoch = None
        setproctitle(name)


    def _interactor_wrapper(self, q: queue.Queue):  # run in a separate thread
        self._rabbitmq_interactor = RabbitmqThreadedSelectLoopInteractor(
            publish_queue=q, consumer_worker_name=self.name
        )
        self._rabbitmq_interactor.run()  # blocking

    def _generic_exit_handler(self, signum, sigframe):
        if signum in [SIGINT, SIGTERM, SIGQUIT] and not self._shutdown_initiated:
            self._shutdown_initiated = True
            self._rabbitmq_interactor.stop()
            raise GenericExitOnSignal

    @rabbitmq_and_redis_cleanup
    def run(self):
        """
        The entry point for the process.
        """
        consensus_epoch_tracker_url = f'{settings.audit_protocol_engine.consensus_url}{settings.audit_protocol_engine.epoch_tracker_path}'
        for signame in [signal.SIGINT, signal.SIGTERM, signal.SIGQUIT]:
            signal.signal(signame, self._generic_exit_handler)
        exchange = f'{settings.RABBITMQ.SETUP.CORE.EXCHANGE}:{settings.NAMESPACE}'
        routing_key = f'epoch-broadcast:{settings.NAMESPACE}:{settings.INSTANCE_ID}'
        self._rabbitmq_thread = threading.Thread(target=self._interactor_wrapper, kwargs={'q': self._rabbitmq_queue})
        self._rabbitmq_thread.start()
        
        sleep_secs_between_chunks = 60

        while True:
            response = requests.get(consensus_epoch_tracker_url)
            if response.status_code != 200:
                self._logger.error('Error while fetching current epoch data: %s', response.status_code)
                sleep(settings.audit_protocol_engine.polling_interval)
                continue
            current_epoch_data = response.json()
            current_epoch = {"begin":current_epoch_data['epochStartBlockHeight'], "end": current_epoch_data['epochEndBlockHeight'], "broadcast_id": str(uuid.uuid4())}
            self._logger.info('Current epoch: %s', current_epoch)
            
            with create_redis_conn(self._connection_pool) as r:
                last_processed_epoch_data = r.get(epoch_detector_last_processed_epoch)
                if last_processed_epoch_data:
                    last_processed_epoch = json.loads(last_processed_epoch_data)
                    if last_processed_epoch['end'] == current_epoch['end']:
                        self._logger.debug('Last processed epoch is same as current epoch, Sleeping for %d seconds...', settings.audit_protocol_engine.polling_interval)
                        sleep(settings.audit_protocol_engine.polling_interval)
                        continue

                    else:
                        fall_behind_reset_threshold = settings.audit_protocol_engine.fall_behind_reset_num_blocks
                        if current_epoch['end'] - last_processed_epoch['end'] > fall_behind_reset_threshold:
                            # TODO: build automatic clean slate procedure, for now just issuing warning on every new epoch fetch
                            self._logger.warning('Epochs are falling behind by more than %d blocks, consider resetting the snapshotter.', fall_behind_reset_threshold)
                        epoch_height = current_epoch['end']-current_epoch['begin']+1
                        
                        if last_processed_epoch['end']> current_epoch['end']:
                            self._logger.warning('Last processed epoch end is greater than current epoch end, something is wrong. Please consider resetting the state.')
                            sys.exit(0)

                        for epoch in chunks(last_processed_epoch['end'], current_epoch['end'], epoch_height):
                            epoch_from_chunk = {'begin': epoch[0], 'end': epoch[1], 'broadcast_id': str(uuid.uuid4())}
                            self._logger.debug('Epoch of sufficient length found: %s', epoch_from_chunk)
                            
                            report_obj = SystemEpochStatusReport(**epoch_from_chunk)
                            self._logger.info('Broadcasting finalized epoch for callbacks: %s', report_obj)
                            brodcast_msg = (report_obj.json().encode('utf-8'), exchange, routing_key)
                            self._rabbitmq_queue.put(brodcast_msg)
                            self._last_processed_epoch = epoch_from_chunk
                            r.set(epoch_detector_last_processed_epoch, json.dumps(epoch_from_chunk))
                            self._logger.info('DONE: Broadcasting finalized epoch for callbacks: %s',
                                            report_obj)
                            
                            self._logger.info('Sleeping for %d seconds...', sleep_secs_between_chunks)
                            sleep(sleep_secs_between_chunks)
                else:
                    self._logger.debug('No last processed epoch found, processing current epoch')
                    
                    report_obj = SystemEpochStatusReport(**current_epoch)
                    self._logger.info('Broadcasting finalized epoch for callbacks: %s', report_obj)
                    brodcast_msg = (report_obj.json().encode('utf-8'), exchange, routing_key)
                    self._rabbitmq_queue.put(brodcast_msg)
                    self.last_processed_epoch = current_epoch
                    self._logger.debug('Setting current epoch as last processed epoch: %s', current_epoch)
                    r.set(epoch_detector_last_processed_epoch, json.dumps(current_epoch))
                    
                    self._logger.info('Sleeping for %d seconds...', settings.audit_protocol_engine.polling_interval)
                    sleep(settings.audit_protocol_engine.polling_interval)
                

if __name__ == '__main__':
    kwargs = dict()
    ps = EpochDetectorProcess(name='PowerLoom|EpochDetector', **kwargs)
    ps.start()