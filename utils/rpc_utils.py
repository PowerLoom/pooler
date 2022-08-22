
import eth_abi
from eth_utils import keccak
from web3 import Web3
import requests
from hexbytes import HexBytes
from dynaconf import settings
import json

RPC_URL = settings.RPC.MATIC[0]

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
    encoded_signature = '0x' + keccak(text=function_signature).hex()
    if len(params) > 0:
        encoded_signature += eth_abi.encode(abi_dict.get(function_name)['input'], params).hex()
    return encoded_signature


def batch_eth_call_on_block_range(abi_dict, function_name, contract_address, from_block='latest', to_block='latest', params=[], from_address=None):
    """
    Batch call "single-function" on a contract for given block-range
    
    RPC_BATCH: for_each_block -> call_function_x
    """
    
    from_address = from_address if from_address else Web3.toChecksumAddress('0x0000000000000000000000000000000000000000')
    function_signature = get_encoded_function_signature(abi_dict, function_name)

    rpc_query = []
    
    if from_block == 'latest' and to_block == 'latest':
        rpc_query.append({
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [
                {
                    "to": contract_address,
                    "data": function_signature
                },
                to_block
            ],
            "id": 1
        })
    else:  
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
                "id": "1"
            })

    rpc_response = []
    response = requests.post(url=RPC_URL, json=rpc_query)
    response = response.json()

    if response[0].get('error', False):
        raise RPCException(
            request={contract_address: contract_address, function_name: function_name, 'params': params, 'from_block': from_block, 'to_block': to_block},
            response=response, underlying_exception=None,
            extra_info=f"RPC_BATCH_ETH_CALL_ERROR: {str(response[0].get('error'))}"
        )
    else:
        response = response if isinstance(response, list) else [response]
        for result in response:
            rpc_response.append(eth_abi.decode(abi_dict.get(function_name)['output'], HexBytes(result['result'])))

    return rpc_response