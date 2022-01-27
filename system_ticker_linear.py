from rpc_helper import ConstructRPC
from message_models import RPCNodesObject, EpochConsensusReport
from init_rabbitmq import create_rabbitmq_conn
from dynaconf import settings
from time import sleep
from multiprocessing import Process
from setproctitle import setproctitle
from proto_system_logging import config_logger_with_namespace
import logging
import logging
import json
import pika


def main_ticker_process(begin=None, end=None):
    # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|EpochTicker|Linear'))
    linear_ticker_logger = logging.getLogger('PowerLoom|EpochTicker|Linear')
    linear_ticker_logger.setLevel(logging.DEBUG)
    linear_ticker_logger.handlers = [logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]
    setproctitle('PowerLoom|SystemEpochClock|Linear')
    c = create_rabbitmq_conn()
    ch = c.channel()
    begin_block_epoch = begin
    end_block_epoch = end
    rpc_obj = ConstructRPC(network_id=137)
    rpc_nodes_obj = RPCNodesObject(
        NODES=settings.RPC.MATIC,
        RETRY_LIMIT=settings.RPC.RETRY
    )
    linear_ticker_logger.debug('Starting %s', Process.name)
    while True:
        cur_block = rpc_obj.rpc_eth_blocknumber(rpc_nodes=rpc_nodes_obj)
        linear_ticker_logger.debug('Got current head of chain: %s', cur_block)
        if not begin_block_epoch:
            begin_block_epoch = cur_block
            linear_ticker_logger.debug('Begin of epoch not set')
            linear_ticker_logger.debug('Set begin of epoch to current head of chain: %s', cur_block)
        else:
            end_block_epoch = cur_block - settings.EPOCH.HEAD_OFFSET
            # linear_ticker_logger.debug('Evaluating possibility to set end of epoch to CHAIN_HEAD - BLOCK_OFFSET: %s', end_block_epoch)
            if end_block_epoch - begin_block_epoch >= settings.EPOCH.HEIGHT:
                _ = {'begin': begin_block_epoch, 'end': end_block_epoch}
                linear_ticker_logger.debug('Epoch of sufficient length found')
                cmd = EpochConsensusReport(**_)
                # send epoch report
                ch.basic_publish(
                    exchange=f'{settings.RABBITMQ.SETUP.CORE.EXCHANGE}:{settings.NAMESPACE}',
                    routing_key=f'epoch-consensus:{settings.NAMESPACE}',
                    body=cmd.json(),
                    properties=pika.BasicProperties(
                        delivery_mode=2,
                        content_type='text/plain',
                        content_encoding='utf-8'
                    ),
                    mandatory=True
                )
                linear_ticker_logger.debug(cmd)
                begin_block_epoch = end_block_epoch + 1
                linear_ticker_logger.debug('Waiting to build next epoch...')
        sleep(settings.EPOCH.BLOCK_TIME)


