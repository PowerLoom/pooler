import asyncio
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

from setproctitle import setproctitle
from web3 import Web3

from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.exceptions import GenericExitOnSignal
from pooler.utils.file_utils import read_json_file
from pooler.utils.models.data_models import AggregateFinalizedEvent
from pooler.utils.models.data_models import EpochReleasedEvent
from pooler.utils.models.data_models import EventBase
from pooler.utils.models.data_models import IndexFinalizedEvent
from pooler.utils.models.data_models import SnapshotFinalizedEvent
from pooler.utils.rabbitmq_helpers import RabbitmqThreadedSelectLoopInteractor
from pooler.utils.redis.redis_conn import RedisPoolCache
from pooler.utils.redis.redis_keys import event_detector_last_processed_block
from pooler.utils.rpc import get_event_sig_and_abi
from pooler.utils.rpc import RpcHelper


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
        Initializes a new instance of the `EpochDetectorProcess` class.

        Arguments:
        name -- the name of the process
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
        setproctitle(name)

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

        # Event Structures
        # event EpochReleased(uint256 begin, uint256 end, uint256 indexed timestamp);
        # event SnapshotFinalized(uint256 epochEnd, string projectId, string snapshotCid, uint256 indexed timestamp);
        # event IndexFinalized(string projectId, uint256 DAGBlockHeight, uint256 indexTailDAGBlockHeight,
        #     uint256 tailBlockEpochSourceChainHeight, bytes32 indexIdentifierHash, uint256 indexed timestamp);
        # event AggregateFinalized(uint256 epochEnd, string projectId, string aggregateCid, uint256 indexed timestamp);

        EVENTS_ABI = {
            'EpochReleased': self.contract.events.EpochReleased._get_event_abi(),
            'SnapshotFinalized': self.contract.events.SnapshotFinalized._get_event_abi(),
            'IndexFinalized': self.contract.events.IndexFinalized._get_event_abi(),
            'AggregateFinalized': self.contract.events.AggregateFinalized._get_event_abi(),
        }

        EVENT_SIGS = {
            'EpochReleased': 'EpochReleased(uint256,uint256,uint256)',
            'SnapshotFinalized': 'SnapshotFinalized(uint256,string,string,uint256)',
            'IndexFinalized': 'IndexFinalized(string,uint256,uint256,uint256,bytes32,uint256)',
            'AggregateFinalized': 'AggregateFinalized(uint256,string,string,uint256)',
        }

        self.event_sig, self.event_abi = get_event_sig_and_abi(
            EVENT_SIGS,
            EVENTS_ABI,
        )

    async def _init_redis_pool(self):
        if not self._aioredis_pool:
            self._aioredis_pool = RedisPoolCache()
            await self._aioredis_pool.populate()
            self._redis_conn = self._aioredis_pool._aioredis_pool

    async def get_events(self, from_block: int, to_block: int):
        """Get the events from the block range.

        Arguments:
            int : from block
            int: to block

        Returns:
            list : (type, event)
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
        for log in events_log:
            if log.event == 'EpochReleased':
                event = EpochReleasedEvent(
                    begin=log.args.begin,
                    end=log.args.end,
                    timestamp=log.args.timestamp,
                    broadcastId=str(uuid.uuid4()),
                )
                events.append((log.event, event))

            elif log.event == 'SnapshotFinalized':
                event = SnapshotFinalizedEvent(
                    DAGBlockHeight=log.args.DAGBlockHeight,
                    projectId=log.args.projectId,
                    snapshotCid=log.args.snapshotCid,
                    timestamp=log.args.timestamp,
                    broadcastId=str(uuid.uuid4()),
                )
                events.append((log.event, event))

            elif log.event == 'IndexFinalized':
                event = IndexFinalizedEvent(
                    projectId=log.args.projectId,
                    DAGBlockHeight=log.args.DAGBlockHeight,
                    indexTailDAGBlockHeight=log.args.indexTailDAGBlockHeight,
                    tailBlockEpochSourceChainHeight=log.args.tailBlockEpochSourceChainHeight,
                    indexIdentifierHash='0x' + log.args.indexIdentifierHash.hex(),
                    timestamp=log.args.timestamp,
                    broadcastId=str(uuid.uuid4()),
                )
                events.append((log.event, event))
            elif log.event == 'AggregateFinalized':
                event = AggregateFinalizedEvent(
                    DAGBlockHeight=log.args.epochEnd,
                    projectId=log.args.projectId,
                    aggregateCid=log.args.aggregateCid,
                    timestamp=log.args.timestamp,
                    broadcastId=str(uuid.uuid4()),
                )
                events.append((log.event, event))

        self._logger.info('Events: {}', events)
        return events

    def _interactor_wrapper(self, q: queue.Queue):  # run in a separate thread
        self._rabbitmq_interactor = RabbitmqThreadedSelectLoopInteractor(
            publish_queue=q,
            consumer_worker_name=self.name,
        )
        self._rabbitmq_interactor.run()  # blocking

    def _generic_exit_handler(self, signum, sigframe):
        if (
            signum in [SIGINT, SIGTERM, SIGQUIT] and
            not self._shutdown_initiated
        ):
            self._shutdown_initiated = True
            self._rabbitmq_interactor.stop()
            raise GenericExitOnSignal

    def _broadcast_event(self, event_type: str, event: EventBase):
        """Broadcast event to the RabbitMQ queue and save update in redis."""
        self._logger.info('Broadcasting event: {}', event)
        brodcast_msg = (
            event.json().encode('utf-8'),
            self._exchange,
            f'{self._routing_key_prefix}{event_type}',
        )
        self._rabbitmq_queue.put(brodcast_msg)

    async def _detect_events(self):
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

            if self._last_processed_block:
                if current_block - self._last_processed_block >= 10:
                    self._logger.warning(
                        'Last processed block is too far behind current block, '
                        'processing current block',
                    )
                    self._last_processed_block = current_block - 1
                # Get events from current block to last_processed_block
                events = await self.get_events(self._last_processed_block + 1, current_block)
            else:

                self._logger.debug(
                    'No last processed epoch found, processing current block',
                )
                events = await self.get_events(current_block, current_block)

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
