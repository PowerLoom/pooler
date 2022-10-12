from signal import SIGINT, SIGTERM, SIGQUIT, signal
import signal
import time
import queue
import threading
import logging
import sys
from functools import wraps
from time import sleep
from multiprocessing import Process

from dynaconf import settings
from setproctitle import setproctitle

from exceptions import GenericExitOnSignal
from rpc_helper import ConstructRPC
from message_models import RPCNodesObject, EpochConsensusReport
from rabbitmq_helpers import RabbitmqThreadedSelectLoopInteractor



def chunks(start_idx, stop_idx, n):
    run_idx = 0
    for i in range(start_idx, stop_idx + 1, n):
        # Create an index range for l of n items:
        begin_idx = i  # if run_idx == 0 else i+1
        if begin_idx == stop_idx + 1:
            return
        end_idx = i + n - 1 if i + n - 1 <= stop_idx else stop_idx
        run_idx += 1
        yield begin_idx, end_idx, run_idx


def rabbitmq_cleanup(fn):
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            fn(self, *args, **kwargs)
        except (GenericExitOnSignal, KeyboardInterrupt):
            try:
                self._logger.debug('Waiting for RabbitMQ interactor thread to join...')
                self._rabbitmq_thread.join()
                self._logger.debug('Shutting down after sending out last epoch with end block height as %s,'
                                    ' starting blockHeight to be used during next restart is %s'
                                    ,self.last_sent_block
                                    , self.last_sent_block+1)
            except:
                pass
        finally:
            sys.exit(0)
    return wrapper


class LinearTickerProcess(Process):
    def __init__(self, name, **kwargs):
        Process.__init__(self, name=name)
        self._rabbitmq_thread: threading.Thread
        self._rabbitmq_queue = queue.Queue()
        self._begin = kwargs.get('begin')
        self._end = kwargs.get('end')
        self._shutdown_initiated = False
        self.last_sent_block = 0

    def _interactor_wrapper(self, q: queue.Queue):
        self._rabbitmq_interactor = RabbitmqThreadedSelectLoopInteractor(
            publish_queue=q, consumer_worker_name=self.name
        )
        self._rabbitmq_interactor.run()

    def _generic_exit_handler(self, signum, sigframe):
        if signum in [SIGINT, SIGTERM, SIGQUIT] and not self._shutdown_initiated:
            self._shutdown_initiated = True
            self._rabbitmq_interactor.stop()
            raise GenericExitOnSignal

    @rabbitmq_cleanup
    def run(self):
        # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|EpochCollator'))
        for signame in [signal.SIGINT, signal.SIGTERM, signal.SIGQUIT]:
            signal.signal(signame, self._generic_exit_handler)
        exchange = f'{settings.RABBITMQ.SETUP.CORE.EXCHANGE}:{settings.NAMESPACE}'
        routing_key = f'epoch-consensus:{settings.NAMESPACE}:{settings.INSTANCE_ID}'
        self._rabbitmq_thread = threading.Thread(target=self._interactor_wrapper, kwargs={'q': self._rabbitmq_queue})
        self._rabbitmq_thread.start()
        # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|EpochTicker|Linear'))
        self._logger = logging.getLogger(f'PowerLoom|EpochTicker|Linear:{settings.NAMESPACE}-{settings.INSTANCE_ID}')
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers = [
            logging.handlers.SocketHandler(
                host=settings.get('LOGGING_SERVER.HOST', 'localhost'),
                port=settings.get('LOGGING_SERVER.PORT', logging.handlers.DEFAULT_TCP_LOGGING_PORT)
            )
        ]
        setproctitle(f'PowerLoom|EpochTicker|Linear:{settings.NAMESPACE}-{settings.INSTANCE_ID}')
        begin_block_epoch = self._begin
        end_block_epoch = self._end
        sleep_secs_between_chunks = 60
        rpc_obj = ConstructRPC(network_id=settings.CHAIN_ID)
        rpc_urls = []
        for node in settings.RPC.FULL_NODES:
            self._logger.debug("node %s",node.url)
            rpc_urls.append(node.url)
        rpc_nodes_obj = RPCNodesObject(
            NODES=rpc_urls,
            RETRY_LIMIT=settings.RPC.RETRY
        )
        self._logger.debug('Starting %s', Process.name)
        while True:
            try:
                cur_block = rpc_obj.rpc_eth_blocknumber(rpc_nodes=rpc_nodes_obj)
            except Exception as ex:
                self._logger.error(
                    "Unable to fetch latest block number due to RPC failure %s. Retrying after %s seconds.",ex,settings.EPOCH.BLOCK_TIME)
                sleep(settings.EPOCH.BLOCK_TIME)
                continue
            else:
                self._logger.debug('Got current head of chain: %s', cur_block)
                if not begin_block_epoch:
                    self._logger.debug('Begin of epoch not set')
                    begin_block_epoch = cur_block
                    self._logger.debug('Set begin of epoch to current head of chain: %s', cur_block)
                    self._logger.debug('Sleeping for: %s seconds', settings.EPOCH.BLOCK_TIME)
                    sleep(settings.EPOCH.BLOCK_TIME)
                else:
                    # self._logger.debug('Picked begin of epoch: %s', begin_block_epoch)
                    end_block_epoch = cur_block - settings.EPOCH.HEAD_OFFSET
                    if not (end_block_epoch - begin_block_epoch + 1) >= settings.EPOCH.HEIGHT:
                        sleep_factor = settings.EPOCH.HEIGHT - ((end_block_epoch - begin_block_epoch) + 1)
                        self._logger.debug('Current head of source chain estimated at block %s after offsetting | '
                                                   '%s - %s does not satisfy configured epoch length. '
                                                   'Sleeping for %s seconds for %s blocks to accumulate....',
                                                   end_block_epoch, begin_block_epoch, end_block_epoch,
                                                   sleep_factor*settings.EPOCH.BLOCK_TIME, sleep_factor
                                                   )
                        time.sleep(sleep_factor * settings.EPOCH.BLOCK_TIME)
                        continue
                    self._logger.debug('Chunking blocks between %s - %s with chunk size: %s', begin_block_epoch,
                                               end_block_epoch, settings.EPOCH.HEIGHT)
                    for epoch in chunks(begin_block_epoch, end_block_epoch, settings.EPOCH.HEIGHT):
                        if epoch[1] - epoch[0] + 1 < settings.EPOCH.HEIGHT:
                            self._logger.debug(
                                'Skipping chunk of blocks %s - %s as minimum epoch size not satisfied | Resetting chunking'
                                ' to begin from block %s',
                                epoch[0], epoch[1], epoch[0]
                            )
                            begin_block_epoch = epoch[0]
                            break
                        _ = {'begin': epoch[0], 'end': epoch[1]}
                        self._logger.debug('Epoch of sufficient length found: %s', _)
                        cmd = EpochConsensusReport(**_)
                        cmd_obj = (cmd.json().encode('utf-8'), exchange, routing_key)
                        self._rabbitmq_queue.put(cmd_obj)
                        # send epoch report
                        self._logger.debug(cmd)
                        self.last_sent_block = epoch[1]
                        self._logger.debug('Waiting to push next epoch in %d seconds...', sleep_secs_between_chunks)
                        # fixed wait
                        sleep(sleep_secs_between_chunks)
                    else:
                        begin_block_epoch = end_block_epoch + 1