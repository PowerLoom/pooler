import json
import multiprocessing
import queue
import signal
import sys
import threading
import uuid
from functools import wraps
from signal import SIGINT
from signal import SIGQUIT
from signal import SIGTERM
from time import sleep

import redis
import requests
from setproctitle import setproctitle

from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.exceptions import GenericExitOnSignal
from pooler.utils.models.data_models import EpochInfo
from pooler.utils.models.message_models import SystemEpochStatusReport
from pooler.utils.rabbitmq_helpers import RabbitmqThreadedSelectLoopInteractor
from pooler.utils.redis.redis_conn import create_redis_conn
from pooler.utils.redis.redis_conn import REDIS_CONN_CONF
from pooler.utils.redis.redis_keys import epoch_detector_last_processed_epoch


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
                        r.set(
                            epoch_detector_last_processed_epoch,
                            json.dumps(self._last_processed_epoch),
                        )
            except Exception as E:
                self._logger.opt(exception=True).error('Error while saving progress: %s', E)
        except Exception as E:
            self._logger.opt(exception=True).error('Error while running: %s', E)
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
        self._logger = logger.bind(
            module=f'{name}|{settings.namespace}-{settings.instance_id[:5]}',
        )

        self._exchange = f'{settings.rabbitmq.setup.core.exchange}:{settings.namespace}'
        self._routing_key = f'epoch-broadcast:{settings.namespace}:{settings.instance_id}'

        self._last_processed_epoch = None
        setproctitle(name)

    def _interactor_wrapper(self, q: queue.Queue):  # run in a separate thread
        self._rabbitmq_interactor = RabbitmqThreadedSelectLoopInteractor(
            publish_queue=q, consumer_worker_name=self.name,
        )
        self._rabbitmq_interactor.run()  # blocking

    def _generic_exit_handler(self, signum, sigframe):
        if signum in [SIGINT, SIGTERM, SIGQUIT] and not self._shutdown_initiated:
            self._shutdown_initiated = True
            self._rabbitmq_interactor.stop()
            raise GenericExitOnSignal

    def _broadcast_epoch(self, epoch: dict):
        """Broadcast epoch to the RabbitMQ queue and save update in redis."""
        report_obj = SystemEpochStatusReport(**epoch)
        self._logger.info('Broadcasting  epoch for callbacks: %s', report_obj)
        brodcast_msg = (report_obj.json().encode('utf-8'), self._exchange, self._routing_key)
        self._rabbitmq_queue.put(brodcast_msg)
        self._last_processed_epoch = epoch
        with create_redis_conn(self._connection_pool) as r:
            try:
                r.set(epoch_detector_last_processed_epoch, json.dumps(epoch))
                self._logger.info(
                    'DONE: Broadcasting finalized epoch for callbacks: %s',
                    report_obj,
                )
            except:
                self._logger.error(
                    'Unable to save state in redis. Will try again on next epoch.',
                )

    @rabbitmq_and_redis_cleanup
    def run(self):
        """
        The entry point for the process.
        """
        consensus_epoch_tracker_url = f'{settings.consensus.url}{settings.consensus.epoch_tracker_path}'
        for signame in [signal.SIGINT, signal.SIGTERM, signal.SIGQUIT]:
            signal.signal(signame, self._generic_exit_handler)
        self._rabbitmq_thread = threading.Thread(
            target=self._interactor_wrapper, kwargs={'q': self._rabbitmq_queue},
        )
        self._rabbitmq_thread.start()

        while True:
            try:
                response = requests.get(consensus_epoch_tracker_url)
                if response.status_code != 200:
                    self._logger.error(
                        'Error while fetching current epoch data: %s', response.status_code,
                    )
                    sleep(settings.consensus.polling_interval)
                    continue
            except Exception as E:
                self._logger.error(
                    f'Unable to fetch current epoch, ERROR: {E}, sleeping for {settings.consensus.polling_interval} seconds.',
                )
                sleep(settings.consensus.polling_interval)
                continue
            epoch_info = EpochInfo(**response.json())
            current_epoch = {
                'begin': epoch_info.epochStartBlockHeight,
                'end': epoch_info.epochEndBlockHeight, 'broadcast_id': str(uuid.uuid4()),
            }
            self._logger.info('Current epoch: %s', current_epoch)

            # Only use redis is state is not locally present
            if not self._last_processed_epoch:
                with create_redis_conn(self._connection_pool) as r:
                    last_processed_epoch_data = r.get(epoch_detector_last_processed_epoch)
                if last_processed_epoch_data:
                    self._last_processed_epoch = json.loads(last_processed_epoch_data)

            if self._last_processed_epoch:
                if self._last_processed_epoch['end'] == current_epoch['end']:
                    self._logger.debug(
                        'Last processed epoch is same as current epoch, Sleeping for %d seconds...', settings.consensus.polling_interval,
                    )
                    sleep(settings.consensus.polling_interval)
                    continue

                else:
                    fall_behind_reset_threshold = settings.consensus.fall_behind_reset_num_blocks
                    if current_epoch['end'] - self._last_processed_epoch['end'] > fall_behind_reset_threshold:
                        # TODO: build automatic clean slate procedure, for now just issuing warning on every new epoch fetch
                        self._logger.error(
                            'Epochs are falling behind by more than %d blocks, consider reset state to continue.', fall_behind_reset_threshold,
                        )
                        raise GenericExitOnSignal
                    epoch_height = current_epoch['end'] - current_epoch['begin'] + 1

                    if self._last_processed_epoch['end'] > current_epoch['end']:
                        self._logger.warning(
                            'Last processed epoch end is greater than current epoch end, something is wrong. Please consider resetting the state.',
                        )
                        raise GenericExitOnSignal

                    for epoch in chunks(self._last_processed_epoch['end'] + 1, current_epoch['end'], epoch_height):
                        epoch_from_chunk = {
                            'begin': epoch[0], 'end': epoch[1], 'broadcast_id': str(uuid.uuid4()),
                        }

                        self._broadcast_epoch(epoch_from_chunk)
                        self._logger.info(
                            'Sleeping for %d seconds...',
                            settings.consensus.sleep_secs_between_chunks,
                        )
                        sleep(settings.consensus.sleep_secs_between_chunks)
            else:
                self._logger.debug('No last processed epoch found, processing current epoch')
                self._broadcast_epoch(current_epoch)

                self._logger.info(
                    'Sleeping for %d seconds...',
                    settings.consensus.polling_interval,
                )
                sleep(settings.consensus.polling_interval)
