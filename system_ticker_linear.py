import time

from rpc_helper import ConstructRPC
from message_models import RPCNodesObject, EpochConsensusReport
from init_rabbitmq import create_rabbitmq_conn
from dynaconf import settings
from time import sleep
from multiprocessing import Process
from setproctitle import setproctitle
from rabbitmq_helpers import resume_on_rabbitmq_fail, RabbitmqThreadedSelectLoopInteractor
import queue
import logging
import threading
import logging
import json
import pika


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


def interactor_wrapper_obj(q: queue.Queue):
    s = RabbitmqThreadedSelectLoopInteractor(publish_queue=q)
    s.run()


def main_ticker_process(begin=None, end=None):
    exchange = f'{settings.RABBITMQ.SETUP.CORE.EXCHANGE}:{settings.NAMESPACE}'
    routing_key = f'epoch-consensus:{settings.NAMESPACE}'

    q = queue.Queue()
    t = threading.Thread(target=interactor_wrapper_obj, kwargs={'q': q})
    t.start()
    # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|EpochTicker|Linear'))
    linear_ticker_logger = logging.getLogger('PowerLoom|EpochTicker|Linear')
    linear_ticker_logger.setLevel(logging.DEBUG)
    linear_ticker_logger.handlers = [
        logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]
    setproctitle('PowerLoom|SystemEpochClock|Linear')
    begin_block_epoch = begin
    end_block_epoch = end
    sleep_secs_between_chunks = 60
    rpc_obj = ConstructRPC(network_id=137)
    rpc_nodes_obj = RPCNodesObject(
        NODES=settings.RPC.MATIC,
        RETRY_LIMIT=settings.RPC.RETRY
    )
    linear_ticker_logger.debug('Starting %s', Process.name)
    while True:
        try:
            cur_block = rpc_obj.rpc_eth_blocknumber(rpc_nodes=rpc_nodes_obj)
        except Exception as e:
            linear_ticker_logger.error(
                f"Unable to fetch latest block number due to RPC failure {e}. Retrying after {settings.EPOCH.BLOCK_TIME} seconds.")
            sleep(settings.EPOCH.BLOCK_TIME)
            continue
        else:
            linear_ticker_logger.debug('Got current head of chain: %s', cur_block)
            if not begin_block_epoch:
                linear_ticker_logger.debug('Begin of epoch not set')
                begin_block_epoch = cur_block
                linear_ticker_logger.debug('Set begin of epoch to current head of chain: %s', cur_block)
                linear_ticker_logger.debug('Sleeping for: %s seconds', settings.EPOCH.BLOCK_TIME)
                sleep(settings.EPOCH.BLOCK_TIME)
            else:
                # linear_ticker_logger.debug('Picked begin of epoch: %s', begin_block_epoch)
                end_block_epoch = cur_block - settings.EPOCH.HEAD_OFFSET
                if not (end_block_epoch - begin_block_epoch + 1) >= settings.EPOCH.HEIGHT:
                    sleep_factor = settings.EPOCH.HEIGHT - ((end_block_epoch - begin_block_epoch) + 1)
                    linear_ticker_logger.debug('Current head of source chain estimated at block %s after offsetting | '
                                               '%s - %s does not satisfy configured epoch length. '
                                               'Sleeping for %s seconds for %s blocks to accumulate....',
                                               end_block_epoch, begin_block_epoch, end_block_epoch,
                                               sleep_factor*settings.EPOCH.BLOCK_TIME, sleep_factor
                                               )
                    time.sleep(sleep_factor * settings.EPOCH.BLOCK_TIME)
                    continue
                linear_ticker_logger.debug('Chunking blocks between %s - %s with chunk size: %s', begin_block_epoch,
                                           end_block_epoch, settings.EPOCH.HEIGHT)
                for epoch in chunks(begin_block_epoch, end_block_epoch, settings.EPOCH.HEIGHT):
                    if epoch[1] - epoch[0] + 1 < settings.EPOCH.HEIGHT:
                        linear_ticker_logger.debug(
                            'Skipping chunk of blocks %s - %s as minimum epoch size not satisfied | Resetting chunking'
                            ' to begin from block %s',
                            epoch[0], epoch[1], epoch[0]
                        )
                        begin_block_epoch = epoch[0]
                        break
                    _ = {'begin': epoch[0], 'end': epoch[1]}
                    linear_ticker_logger.debug('Epoch of sufficient length found: %s', _)
                    cmd = EpochConsensusReport(**_)
                    cmd_obj = (cmd.json().encode('utf-8'), exchange, routing_key)
                    q.put(cmd_obj)
                    # send epoch report
                    linear_ticker_logger.debug(cmd)
                    linear_ticker_logger.debug('Waiting to push next epoch in %d seconds...', sleep_secs_between_chunks)
                    # fixed wait
                    sleep(sleep_secs_between_chunks)
                else:
                    begin_block_epoch = end_block_epoch + 1
