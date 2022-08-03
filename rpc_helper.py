from itertools import repeat
from message_models import RPCNodesObject
from functools import wraps
import requests
import time
import logging
import logging.handlers
import multiprocessing
import sys
import tenacity
from dynaconf import settings

formatter = logging.Formatter('%(levelname)-8s %(name)-4s %(asctime)s,%(msecs)d %(module)s-%(funcName)s: %(message)s')
rpc_logger = logging.getLogger('NodeRPCHelper')
rpc_logger.setLevel(logging.DEBUG)
rpc_logger.handlers = [logging.handlers.SocketHandler(host=settings.get('LOGGING_SERVER.HOST','localhost'),
            port=settings.get('LOGGING_SERVER.PORT',logging.handlers.DEFAULT_TCP_LOGGING_PORT))]
# rpc_logger.handlers[0].setFormatter(formatter)


def auto_retry(tries=3, exc=Exception, delay=5):
    def deco(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for _ in range(tries):
                try:
                    return func(*args, **kwargs)
                except exc:
                    time.sleep(delay)
                    continue
            raise exc

        return wrapper

    return deco


class BailException(RuntimeError):
    pass


class MySQLConnectionError(RuntimeError):
    pass


class GracefulSIGTERMExit(Exception):
    def __str__(self):
        return "SIGTERM Exit"

    def __repr__(self):
        return "SIGTERM Exit"


class GracefulSIGDeathExit(Exception):
    def __init__(self, signal_information):
        Exception.__init__(self)
        self._sig = signal_information

    def __str__(self):
        return f"{self._sig} Exit"

    def __repr__(self):
        return f"{self._sig} Exit"


def sigterm_handler(signum, frame):
    raise GracefulSIGTERMExit


def sigkill_handler(signum, frame):
    raise GracefulSIGDeathExit(signum)


class ConstructRPC:
    def __init__(self, network_id):
        self._network_id = network_id
        self._querystring = {"id": network_id, "jsonrpc": "2.0"}

    def sync_post_json_rpc(self, procedure, rpc_nodes: RPCNodesObject, params=None):
        q_s = self.construct_one_timeRPC(procedure=procedure, params=params)
        rpc_urls = rpc_nodes.NODES
        retry = dict(zip(rpc_urls, repeat(0)))
        success = False
        while True:
            if all(val == rpc_nodes.RETRY_LIMIT for val in retry.values()):
                rpc_logger.error("Retry limit reached for all RPC endpoints. Following request")
                rpc_logger.error("%s", q_s)
                rpc_logger.error("%s", retry)
                raise BailException
            for _url in rpc_urls:
                try:
                    retry[_url] += 1
                    r = requests.post(_url, json=q_s, timeout=5)
                    json_response = r.json()
                except (requests.exceptions.Timeout,
                        requests.exceptions.ConnectionError,
                        requests.exceptions.HTTPError):
                    success = False
                except Exception as e:
                    success = False
                else:
                    if procedure == 'eth_getBlockByNumber' and not json_response['result']:
                        continue
                    success = True
                    return json_response

    def rpc_eth_blocknumber(self, rpc_nodes: RPCNodesObject):
        rpc_response = self.sync_post_json_rpc(procedure="eth_blockNumber", rpc_nodes=rpc_nodes)
        try:
            new_blocknumber = int(rpc_response["result"], 16)
        except Exception as e:
            raise BailException
        else:
            return new_blocknumber

    @auto_retry(tries=2, exc=BailException)
    def rpc_eth_getblock_by_number(self, blocknum, rpc_nodes):
        rpc_response = self.sync_post_json_rpc(procedure="eth_getBlockByNumber", rpc_nodes=rpc_nodes,
                                               params=[hex(blocknum), False])
        try:
            blockdetails = rpc_response["result"]
        except Exception as e:
            raise
        else:
            return blockdetails

    @auto_retry(tries=2, exc=BailException)
    def rpc_eth_get_tx_count(self, account, rpc_nodes, block):
        rpc_response = self.sync_post_json_rpc(procedure='eth_getTransactionCount',
                                               params=[account, block],
                                               rpc_nodes=rpc_nodes)
        try:
            tx_count = int(rpc_response["result"], 16)
        except Exception as e:
            raise
        else:
            return tx_count

    @auto_retry(tries=2, exc=BailException)
    def rpc_eth_get_tx_receipt(self, tx, rpc_nodes):
        rpc_response = self.sync_post_json_rpc(procedure="eth_getTransactionReceipt",
                                               rpc_nodes=rpc_nodes,
                                               params=[tx])
        try:
            tx_receipt = rpc_response["result"]
        except KeyError as e:
            process_name = multiprocessing.current_process().name
            rpc_logger.debug("{1}: Unexpected JSON RPC response: {0}".format(rpc_response, process_name))
            raise
        else:
            return tx_receipt

    @auto_retry(tries=2, exc=BailException)
    def rpc_eth_get_tx_by_hash(self, tx, rpc_nodes):
        rpc_response = self.sync_post_json_rpc(procedure="eth_getTransactionByHash",
                                               rpc_nodes=rpc_nodes,
                                               params=[tx])
        try:
            tx_hash = rpc_response["result"]
        except KeyError as e:
            process_name = multiprocessing.current_process().name
            rpc_logger.debug("{1}: Unexpected JSON RPC response: {0}".format(rpc_response, process_name))
            raise
        else:
            return tx_hash

    def construct_one_timeRPC(self, procedure, params, defaultBlock=None):
        self._querystring["method"] = procedure
        self._querystring["params"] = []
        if type(params) is list:
            self._querystring["params"].extend(params)
        elif params is not None:
            self._querystring["params"].append(params)
        if defaultBlock is not None:
            self._querystring["params"].append(defaultBlock)
        return self._querystring
