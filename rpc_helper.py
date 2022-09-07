from itertools import repeat
from message_models import RPCNodesObject
from functools import wraps
import requests
import time
import logging
import logging.handlers
import multiprocessing
from dynaconf import settings
from web3 import Web3
from hexbytes import HexBytes
import eth_abi
from eth_utils import keccak
from web3._utils.events import get_event_data
from eth_abi.codec import ABICodec
import json
from async_limits import parse_many as limit_parse_many
from gnosis.eth import EthereumClient


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

class RPCException(Exception):
    def __init__(self, request, response, underlying_exception, extra_info):
        self.request = request
        self.response = response
        self.underlying_exception: Exception = underlying_exception
        self.extra_info = extra_info

    def __str__(self):
        ret = {
            'request': self.request,
            'response': self.response,
            'extra_info': self.extra_info,
            'exception': None
        }
        if isinstance(self.underlying_exception, Exception):
            ret.update({'exception': self.underlying_exception.__str__()})
        return json.dumps(ret)

    def __repr__(self):
        return self.__str__()



def load_web3_providers_and_rate_limits(full_nodes, archive_nodes):
    web3_providers = {
        "full_nodes":  list(),  
        "archive_nodes": list()
    }

    count=1
    for node in full_nodes:
        web3_providers["full_nodes"].append({
            "web3_client": EthereumClient(node.url),
            "rate_limit": limit_parse_many(node.rate_limit),
            "rpc_url": node.url,
            "index": count
        })

    count=1
    for node in archive_nodes:
        web3_providers["archive_nodes"].append({
            "web3_client": EthereumClient(node.url),
            "rate_limit": limit_parse_many(node.rate_limit),
            "rpc_url": node.url,
            "index": count
        })

    return web3_providers



def contract_abi_dict(abi):
    """
    Create dictionary of ABI {function_name -> {signature, abi, input, output}}
    """
    abi_dict = {}
    for abi_obj in [obj for obj in abi if obj['type'] == 'function']:
        name = abi_obj['name']
        input_types = [input['type'] for input in abi_obj['inputs']]
        output_types = [output['type'] for output in abi_obj['outputs']]
        abi_dict[name] = {
            "signature": '{}({})'.format(name,','.join(input_types)), 
            'output': output_types, 
            'input': input_types, 
            'abi': abi_obj
        }

    return abi_dict


def get_encoded_function_signature(abi_dict, function_name, params: list = []):
    """
    get function encoded signature with params
    """
    function_signature = abi_dict.get(function_name)['signature']
    encoded_signature = '0x' + keccak(text=function_signature).hex()[:8]
    if len(params) > 0:
        encoded_signature += eth_abi.encode_abi(abi_dict.get(function_name)['input'], params).hex()
    return encoded_signature


def batch_eth_call_on_block_range(rpc_endpoint, abi_dict, function_name, contract_address, from_block='latest', to_block='latest', params=[], from_address=None):
    """
    Batch call "single-function" on a contract for given block-range
    
    RPC_BATCH: for_each_block -> call_function_x
    """
    
    from_address = from_address if from_address else Web3.toChecksumAddress('0x0000000000000000000000000000000000000000')
    function_signature = get_encoded_function_signature(abi_dict, function_name, params)
    rpc_query = []

    if from_block == 'latest' and to_block == 'latest':
        rpc_query.append({
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [
                {
                    "to": Web3.toChecksumAddress(contract_address),
                    "data": function_signature
                },
                to_block
            ],
            "id": "1"
        })
    else: 
        request_id = 1
        for block in range(from_block, to_block+1):
            rpc_query.append({
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [
                    {
                        "from": from_address,
                        "to": Web3.toChecksumAddress(contract_address),
                        "data": function_signature,
                    },
                    hex(block)
                ],
                "id": f'{request_id}'
            })
            request_id+=1

    rpc_response = []
    response = requests.post(url=rpc_endpoint, json=rpc_query)
    response = response.json()
    response_exceptions = list(map(lambda r: r, filter(lambda y: y.get('error', False), response))) if isinstance(response, list) else response

    if len(response_exceptions) > 0:
        raise RPCException(
            request={contract_address: contract_address, function_name: function_name, 'params': params, 'from_block': from_block, 'to_block': to_block},
            response=response_exceptions, underlying_exception=None,
            extra_info=f"RPC_BATCH_ETH_CALL_ERRORS: {str(response_exceptions)}"
        )
    else:
        response = response if isinstance(response, list) else [response]
        for result in response:
            rpc_response.append(eth_abi.decode_abi(abi_dict.get(function_name)['output'], HexBytes(result['result'])))

    return rpc_response



def batch_eth_get_block(rpc_endpoint, from_block, to_block):
    """
    Batch call "eth_getBlockByNumber" in a range of block numbers
    
    RPC_BATCH: for_each_block -> eth_getBlockByNumber
    """
    
    rpc_query = []

    request_id = 1
    for block in range(from_block, to_block+1):
        rpc_query.append({
            "jsonrpc": "2.0",
            "method": "eth_getBlockByNumber",
            "params": [
                hex(block),
                True
            ],
            "id": f'{request_id}'
        })
        request_id+=1
        
    response = requests.post(url=rpc_endpoint, json=rpc_query)
    response = response.json()
    response_exceptions = list(map(lambda r: r, filter(lambda y: y.get('error', False), response)))

    if len(response_exceptions) > 0:
        raise RPCException(
            request={'from_block': from_block, 'to_block': to_block},
            response=response_exceptions, underlying_exception=None,
            extra_info=f"RPC_BATCH_ETH_GET_BLOCK_ERRORS: {str(response_exceptions)}"
        )

    return response


def get_event_sig_and_abi(event_signatures, event_abis):
    event_sig = ['0x' + keccak(text=sig).hex() for name, sig in event_signatures.items()]
    event_abi = {'0x' + keccak(text=sig).hex(): event_abis.get(name, 'incorrect event name') for name, sig in event_signatures.items()}
    return event_sig, event_abi


def get_events_logs(web3Provider, contract_address, toBlock, fromBlock, topics, event_abi):
    event_log = web3Provider.eth.get_logs({
        'address': Web3.toChecksumAddress(contract_address),
        'toBlock': toBlock,
        'fromBlock': fromBlock,
        'topics': topics
    })

    codec: ABICodec = web3Provider.codec
    all_events = []
    for log in event_log:
        abi = event_abi.get(log.topics[0].hex(), "") 
        evt = get_event_data(codec, abi, log)
        all_events.append(evt)

    return all_events