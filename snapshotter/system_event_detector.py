import asyncio
import json
import multiprocessing
import queue
import resource
import signal
import sys
import threading
import time
from functools import wraps
from signal import SIGINT
from signal import SIGQUIT
from signal import SIGTERM

from web3 import Web3

from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import logger
from snapshotter.utils.exceptions import GenericExitOnSignal
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.models.data_models import EpochReleasedEvent
from snapshotter.utils.models.data_models import EventBase
from snapshotter.utils.models.data_models import SnapshotFinalizedEvent
from snapshotter.utils.rabbitmq_helpers import RabbitmqThreadedSelectLoopInteractor
from snapshotter.utils.redis.redis_conn import RedisPoolCache
from snapshotter.utils.redis.redis_keys import event_detector_last_processed_block
from snapshotter.utils.redis.redis_keys import last_epoch_detected_timestamp_key
from snapshotter.utils.rpc import get_event_sig_and_abi
from snapshotter.utils.rpc import RpcHelper


def rabbitmq_and_redis_cleanup(fn):
    """
    A decorator function that wraps the given function and handles cleanup of RabbitMQ and Redis connections in case of
    a GenericExitOnSignal or KeyboardInterrupt exception.

    Args:
        fn: The function to be wrapped.

    Returns:
        The wrapped function.
    """
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            fn(self, *args, **kwargs)
        except (GenericExitOnSignal, KeyboardInterrupt):
            try:
                self._logger.debug(
                    'Waiting for RabbitMQ interactor thread to join...',
                )
                self._rabbitmq_thread.join()
                self._logger.debug('RabbitMQ interactor thread joined.')
                if self._last_processed_block:
                    self._logger.debug(
                        'Saving last processed epoch to redis...',
                    )
                    self.ev_loop.run_until_complete(
                        self._redis_conn.set(
                            event_detector_last_processed_block,
                            json.dumps(self._last_processed_block),
                        ),
                    )
            except Exception as E:
                self._logger.opt(exception=True).error(
                    'Error while saving progress: {}', E,
                )
        except Exception as E:
            self._logger.opt(exception=True).error('Error while running: {}', E)
        finally:
            self._logger.debug('Shutting down!')
            sys.exit(0)

    return wrapper


class EventDetectorProcess(multiprocessing.Process):
    _rabbitmq_thread: threading.Thread
    _rabbitmq_queue: queue.Queue

    def __init__(self, name, **kwargs):
        """
        Initializes the SystemEventDetector class.

        Args:
            name (str): The name of the process.
            **kwargs: Additional keyword arguments to be passed to the multiprocessing.Process class.

        Attributes:
            _rabbitmq_thread (threading.Thread): The RabbitMQ thread.
            _rabbitmq_queue (queue.Queue): The RabbitMQ queue.
            _shutdown_initiated (bool): A flag indicating whether shutdown has been initiated.
            _logger (logging.Logger): The logger instance.
            _exchange (str): The exchange name.
            _routing_key_prefix (str): The routing key prefix.
            _aioredis_pool (None): The aioredis pool.
            _redis_conn (None): The redis connection.
            _last_processed_block (None): The last processed block.
            rpc_helper (RpcHelper): The RpcHelper instance.
            contract_abi (dict): The contract ABI.
            contract_address (str): The contract address.
            contract (web3.eth.Contract): The contract instance.
            event_sig (dict): The event signature.
            event_abi (dict): The event ABI.
        """
        multiprocessing.Process.__init__(self, name=name, **kwargs)
        self._rabbitmq_thread: threading.Thread
        self._rabbitmq_queue = queue.Queue()
        self._shutdown_initiated = False
        self._logger = logger.bind(
            module=f'{name}|{settings.namespace}-{settings.instance_id[:5]}',
        )

        self._exchange = (
            f'{settings.rabbitmq.setup.event_detector.exchange}:{settings.namespace}'
        )
        self._routing_key_prefix = (
            f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}.'
        )
        self._aioredis_pool = None
        self._redis_conn = None

        self._last_processed_block = None

        self.rpc_helper = RpcHelper(rpc_settings=settings.anchor_chain_rpc)
        self.contract_abi = read_json_file(
            settings.protocol_state.abi,
            self._logger,
        )
        self.contract_address = settings.protocol_state.address
        self.contract = self.rpc_helper.get_current_node()['web3_client'].eth.contract(
            address=Web3.toChecksumAddress(
                self.contract_address,
            ),
            abi=self.contract_abi,
        )

        # event EpochReleased(uint256 indexed epochId, uint256 begin, uint256 end, uint256 timestamp);
        # event SnapshotFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId,
        # string snapshotCid, uint256 finalizedSnapshotCount, uint256 totalReceivedCount, uint256 timestamp);

        EVENTS_ABI = {
            'EpochReleased': self.contract.events.EpochReleased._get_event_abi(),
            'SnapshotFinalized': self.contract.events.SnapshotFinalized._get_event_abi(),
        }

        EVENT_SIGS = {
            'EpochReleased': 'EpochReleased(uint256,uint256,uint256,uint256)',
            'SnapshotFinalized': 'SnapshotFinalized(uint256,uint256,string,string,uint256,uint256,uint256)',
        }

        self.event_sig, self.event_abi = get_event_sig_and_abi(
            EVENT_SIGS,
            EVENTS_ABI,
        )

    async def _init_redis_pool(self):
        """
        Initializes the Redis connection pool if it hasn't been initialized yet.
        """
        if not self._aioredis_pool:
            self._aioredis_pool = RedisPoolCache()
            await self._aioredis_pool.populate()
            self._redis_conn = self._aioredis_pool._aioredis_pool

    async def get_events(self, from_block: int, to_block: int):
        """
        Retrieves events from the blockchain for the given block range and returns them as a list of tuples.
        Each tuple contains the event name and an object representing the event data.

        Args:
            from_block (int): The starting block number.
            to_block (int): The ending block number.

        Returns:
            List[Tuple[str, Any]]: A list of tuples, where each tuple contains the event name
            and an object representing the event data.
        """
        events_log = await self.rpc_helper.get_events_logs(
            **{
                'contract_address': self.contract_address,
                'to_block': to_block,
                'from_block': from_block,
                'topics': [self.event_sig],
                'event_abi': self.event_abi,
                'redis_conn': self._redis_conn,
            },
        )

        events = []
        new_epoch_detected = False
        for log in events_log:
            if log.event == 'EpochReleased':
                event = EpochReleasedEvent(
                    begin=log.args.begin,
                    end=log.args.end,
                    epochId=log.args.epochId,
                    timestamp=log.args.timestamp,
                )
                new_epoch_detected = True
                events.append((log.event, event))

            elif log.event == 'SnapshotFinalized':
                event = SnapshotFinalizedEvent(
                    epochId=log.args.epochId,
                    epochEnd=log.args.epochEnd,
                    projectId=log.args.projectId,
                    snapshotCid=log.args.snapshotCid,
                    timestamp=log.args.timestamp,
                )
                events.append((log.event, event))

        if new_epoch_detected:
            await self._redis_conn.set(
                last_epoch_detected_timestamp_key(),
                int(time.time()),
            )

        self._logger.info('Events: {}', events)
        return events

    def _interactor_wrapper(self, q: queue.Queue):  # run in a separate thread
        """
        A wrapper method that runs in a separate thread and initializes a RabbitmqThreadedSelectLoopInteractor object.

        Args:
        - q: A queue.Queue object that is used to publish messages to RabbitMQ.
        """
        self._rabbitmq_interactor = RabbitmqThreadedSelectLoopInteractor(
            publish_queue=q,
            consumer_worker_name=self.name,
        )
        self._rabbitmq_interactor.run()  # blocking

    def _generic_exit_handler(self, signum, sigframe):
        """
        Handles the generic exit signal and initiates shutdown.

        Args:
            signum (int): The signal number.
            sigframe (object): The signal frame.

        Raises:
            GenericExitOnSignal: If the shutdown is initiated.
        """
        if (
            signum in [SIGINT, SIGTERM, SIGQUIT] and
            not self._shutdown_initiated
        ):
            self._shutdown_initiated = True
            self._rabbitmq_interactor.stop()
            raise GenericExitOnSignal

    def _broadcast_event(self, event_type: str, event: EventBase):
        """
        Broadcasts the given event to the RabbitMQ queue.

        Args:
            event_type (str): The type of the event being broadcasted.
            event (EventBase): The event being broadcasted.
        """
        self._logger.info('Broadcasting event: {}', event)
        brodcast_msg = (
            event.json().encode('utf-8'),
            self._exchange,
            f'{self._routing_key_prefix}{event_type}',
        )
        self._rabbitmq_queue.put(brodcast_msg)

    async def _detect_events(self):
        """
        Continuously detects events by fetching the current block and comparing it to the last processed block.
        If the last processed block is too far behind the current block, it processes the current block and broadcasts the events.
        The last processed block is saved in Redis for future reference.
        """
        while True:
            try:
                current_block = await self.rpc_helper.get_current_block(redis_conn=self._redis_conn)
                self._logger.info('Current block: {}', current_block)

            except Exception as e:
                self._logger.opt(exception=True).error(
                    (
                        'Unable to fetch current block, ERROR: {}, '
                        'sleeping for {} seconds.'
                    ),
                    e,
                    settings.rpc.polling_interval,
                )

                await asyncio.sleep(settings.rpc.polling_interval)
                continue

            # Only use redis is state is not locally present
            if not self._last_processed_block:
                last_processed_block_data = await self._redis_conn.get(
                    event_detector_last_processed_block,
                )

                if last_processed_block_data:
                    self._last_processed_block = json.loads(
                        last_processed_block_data,
                    )

            if self._last_processed_block == current_block:
                self._logger.info(
                    'No new blocks detected, sleeping for {} seconds...',
                    settings.anchor_chain.polling_interval,
                )
                await asyncio.sleep(settings.anchor_chain.polling_interval)
                continue

            if self._last_processed_block:
                if current_block - self._last_processed_block >= 10:
                    self._logger.warning(
                        'Last processed block is too far behind current block, '
                        'processing current block',
                    )
                    self._last_processed_block = current_block - 10

                # Get events from current block to last_processed_block
                try:
                    events = await self.get_events(self._last_processed_block + 1, current_block)
                except Exception as e:
                    self._logger.opt(exception=True).error(
                        (
                            'Unable to fetch events from block {} to block {}, '
                            'ERROR: {}, sleeping for {} seconds.'
                        ),
                        self._last_processed_block + 1,
                        current_block,
                        e,
                        settings.rpc.polling_interval,
                    )
                    await asyncio.sleep(settings.rpc.polling_interval)
                    continue

            else:

                self._logger.debug(
                    'No last processed epoch found, processing current block',
                )

                try:
                    events = await self.get_events(current_block, current_block)
                except Exception as e:
                    self._logger.opt(exception=True).error(
                        (
                            'Unable to fetch events from block {} to block {}, '
                            'ERROR: {}, sleeping for {} seconds.'
                        ),
                        current_block,
                        current_block,
                        e,
                        settings.rpc.polling_interval,
                    )
                    await asyncio.sleep(settings.rpc.polling_interval)
                    continue

            for event_type, event in events:
                self._logger.info(
                    'Processing event: {}', event,
                )
                self._broadcast_event(event_type, event)

            self._last_processed_block = current_block

            await self._redis_conn.set(event_detector_last_processed_block, json.dumps(current_block))
            self._logger.info(
                'DONE: Processed blocks till, saving in redis: {}',
                current_block,
            )
            self._logger.info(
                'Sleeping for {} seconds...',
                settings.rpc.polling_interval,
            )
            await asyncio.sleep(settings.rpc.polling_interval)

    @rabbitmq_and_redis_cleanup
    def run(self):
        """
        A class for detecting system events using RabbitMQ and Redis.

        Methods:
        --------
        run()
            Starts the event detection process.
        """
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (settings.rlimit.file_descriptors, hard),
        )
        for signame in [signal.SIGINT, signal.SIGTERM, signal.SIGQUIT]:
            signal.signal(signame, self._generic_exit_handler)
        self._rabbitmq_thread = threading.Thread(
            target=self._interactor_wrapper,
            kwargs={'q': self._rabbitmq_queue},
        )
        self.ev_loop = asyncio.get_event_loop()

        self.ev_loop.run_until_complete(
            self._init_redis_pool(),
        )
        self._rabbitmq_thread.start()

        self.ev_loop.run_until_complete(
            self._detect_events(),
        )
