from typing import List
from typing import Union

import eth_abi
from async_limits import parse_many as limit_parse_many
from eth_abi.codec import ABICodec
from eth_utils import keccak
from gnosis.eth import EthereumClient
from hexbytes import HexBytes
from httpx import AsyncClient
from httpx import AsyncHTTPTransport
from httpx import Limits
from httpx import Timeout
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential
from web3 import Web3
from web3._utils.events import get_event_data

from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.exceptions import RPCException
from pooler.utils.redis.rate_limiter import check_rpc_rate_limit
from pooler.utils.redis.rate_limiter import load_rate_limiter_scripts


def get_contract_abi_dict(abi):
    """
    Create dictionary of ABI {function_name -> {signature, abi, input, output}}
    """
    abi_dict = {}
    for abi_obj in [obj for obj in abi if obj['type'] == 'function']:
        name = abi_obj['name']
        input_types = [input['type'] for input in abi_obj['inputs']]
        output_types = [output['type'] for output in abi_obj['outputs']]
        abi_dict[name] = {
            'signature': '{}({})'.format(name, ','.join(input_types)),
            'output': output_types,
            'input': input_types,
            'abi': abi_obj,
        }

    return abi_dict


def get_encoded_function_signature(abi_dict, function_name, params: Union[List, None]):
    """
    get function encoded signature with params
    """
    function_signature = abi_dict.get(function_name)['signature']
    encoded_signature = '0x' + keccak(text=function_signature).hex()[:8]
    if params:
        encoded_signature += eth_abi.encode_abi(
            abi_dict.get(function_name)['input'],
            params,
        ).hex()
    return encoded_signature


def get_event_sig_and_abi(event_signatures, event_abis):
    event_sig = [
        '0x' + keccak(text=sig).hex() for name, sig in event_signatures.items()
    ]
    event_abi = {
        '0x' +
        keccak(text=sig).hex(): event_abis.get(
            name,
            'incorrect event name',
        )
        for name, sig in event_signatures.items()
    }
    return event_sig, event_abi


class RpcHelper(object):
    def __init__(self, archive_mode=False):
        self._archive_mode = archive_mode

        self._nodes = list()
        self._current_node_index = -1
        self._node_count = 0
        self._rate_limit_lua_script_shas = None
        self._nodes_initialized = False
        self._initialized = False
        self._logger = logger.bind(module='PowerLoom|RPCHelper')
        self._client = None
        self._async_transport = None
        self._rate_limit_lua_script_shas = None

    async def _load_rate_limit_shas(self, redis_conn):
        if self._rate_limit_lua_script_shas is not None:
            return
        self._rate_limit_lua_script_shas = await load_rate_limiter_scripts(
            redis_conn,
        )

    async def _init_httpx_client(self):
        if self._client is not None:
            return
        self._async_transport = AsyncHTTPTransport(
            limits=Limits(
                max_connections=100,
                max_keepalive_connections=50,
                keepalive_expiry=None,
            ),
        )
        self._client = AsyncClient(
            timeout=Timeout(timeout=5.0),
            follow_redirects=False,
            transport=self._async_transport,
        )

    async def init(self, redis_conn):
        await self._load_rate_limit_shas(redis_conn)
        await self._init_httpx_client()
        self._initialized = True

    def _load_web3_providers_and_rate_limits(self):
        if self._archive_mode:
            nodes = settings.rpc.archive_nodes
        else:
            nodes = settings.rpc.full_nodes

        for node in nodes:
            try:
                self._nodes.append(
                    {
                        'web3_client': EthereumClient(node.url),
                        'rate_limit': limit_parse_many(node.rate_limit),
                        'rpc_url': node.url,
                    },
                )
            except Exception as exc:

                self._logger.opt(exception=True).error(
                    (
                        'Error while initialising one of the web3 providers,'
                        f' err_msg: {exc}'
                    ),
                )

        if self._nodes:
            self._current_node_index = 0
            self._node_count = len(self._nodes)

    def get_current_node(self):
        if not self._nodes_initialized:
            self._load_web3_providers_and_rate_limits()
            self._nodes_initialized = True

        if self._current_node_index == -1:
            raise Exception('No full nodes available')
        return self._nodes[self._current_node_index]

    def _on_node_exception(self, retry_state):
        self._current_node_index = (self._current_node_index + 1) % self._node_count
        self._logger.warning(
            (
                'Found exception injected next full_node | exception:'
                f' {retry_state.outcome.exception()} |'
                f' function:{retry_state.fn}'
            ),
        )

    async def web3_call(self, tasks, redis_conn):
        """
        Call web3 functions in parallel
        """
        if not self._initialized:
            await self.init(redis_conn)

        @retry(
            reraise=True,
            retry=retry_if_exception_type(RPCException),
            wait=wait_random_exponential(multiplier=1, max=10),
            stop=stop_after_attempt(settings.rpc.retry),
            before_sleep=self._on_node_exception,
        )
        async def f():
            node = self.get_current_node()
            rpc_url = node.get('rpc_url')

            await check_rpc_rate_limit(
                parsed_limits=node.get('rate_limit', []),
                app_id=rpc_url.split('/')[-1],
                redis_conn=redis_conn,
                request_payload=[task.fn_name for task in tasks],
                error_msg={
                    'msg': 'exhausted_api_key_rate_limit inside web3_call',
                },
                logger=self._logger,
                rate_limit_lua_script_shas=self._rate_limit_lua_script_shas,
                limit_incr_by=len(tasks),
            )
            try:
                response = node['web3_client'].batch_call(tasks)
                return response
            except Exception as e:
                exc = RPCException(
                    request=[task.fn_name for task in tasks],
                    response=None,
                    underlying_exception=e,
                    extra_info={'msg': str(e)},
                )

                self._logger.opt(lazy=True).trace(
                    (
                        'Error while making web3 batch call'
                    ),
                    err=lambda: str(exc),
                )
                raise exc
        return await f()

    async def batch_eth_call_on_block_range(
        self,
        abi_dict,
        function_name,
        contract_address,
        redis_conn,
        from_block='latest',
        to_block='latest',
        params: Union[List, None] = None,
        from_address=Web3.toChecksumAddress('0x0000000000000000000000000000000000000000'),
    ):
        """
        Batch call "single-function" on a contract for given block-range

        RPC_BATCH: for_each_block -> call_function_x
        """
        if not self._initialized:
            await self.init(redis_conn)

        if params is None:
            params = []

        @retry(
            reraise=True,
            retry=retry_if_exception_type(RPCException),
            wait=wait_random_exponential(multiplier=1, max=10),
            stop=stop_after_attempt(settings.rpc.retry),
            before_sleep=self._on_node_exception,
        )
        async def f():
            function_signature = get_encoded_function_signature(
                abi_dict, function_name, params,
            )
            rpc_query = []

            if from_block == 'latest' and to_block == 'latest':
                rpc_query.append(
                    {
                        'jsonrpc': '2.0',
                        'method': 'eth_call',
                        'params': [
                            {
                                'to': Web3.toChecksumAddress(contract_address),
                                'data': function_signature,
                            },
                            to_block,
                        ],
                        'id': 1,
                    },
                )
            else:
                request_id = 1
                for block in range(from_block, to_block + 1):
                    rpc_query.append(
                        {
                            'jsonrpc': '2.0',
                            'method': 'eth_call',
                            'params': [
                                {
                                    'from': from_address,
                                    'to': Web3.toChecksumAddress(contract_address),
                                    'data': function_signature,
                                },
                                hex(block),
                            ],
                            'id': request_id,
                        },
                    )
                    request_id += 1

            node = self.get_current_node()
            rpc_url = node.get('rpc_url')

            await check_rpc_rate_limit(
                parsed_limits=node.get('rate_limit', []),
                app_id=rpc_url.split('/')[-1],
                redis_conn=redis_conn,
                request_payload=rpc_query,
                error_msg={
                    'msg': 'exhausted_api_key_rate_limit inside batch_eth_call_on_block_range',
                },
                logger=self._logger,
                rate_limit_lua_script_shas=self._rate_limit_lua_script_shas,
                limit_incr_by=len(rpc_query),
            )

            rpc_response = []
            try:
                response = await self._client.post(url=rpc_url, json=rpc_query)
                response_data = response.json()
            except Exception as e:
                exc = RPCException(
                    request={
                        contract_address: contract_address,
                        function_name: function_name,
                        'params': params,
                        'from_block': from_block,
                        'to_block': to_block,
                    },
                    response=None,
                    underlying_exception=e,
                    extra_info=f'RPC_BATCH_ETH_CALL_ERROR: {str(e)}',
                )
                self._logger.trace(
                    'Error in batch_eth_call_on_block_range, error {}', str(exc),
                )
                raise exc

            if response.status_code != 200:
                raise RPCException(
                    request={
                        'from_block': from_block,
                        'to_block': to_block,
                    },
                    response=(response.status_code, response.text),
                    underlying_exception=None,
                    extra_info=f'RPC_BATCH_ETH_CALL_ERROR: {response.text}',
                )

            response_exceptions = (
                list(
                    map(
                        lambda r: r,
                        filter(
                            lambda y: y.get(
                                'error',
                                False,
                            ),
                            response_data,
                        ),
                    ),
                )
                if isinstance(response_data, list)
                else response_data
            )

            if len(response_exceptions) > 0:
                exc = RPCException(
                    request={
                        contract_address: contract_address,
                        function_name: function_name,
                        'params': params,
                        'from_block': from_block,
                        'to_block': to_block,
                    },
                    response=response_exceptions,
                    underlying_exception=None,
                    extra_info=f'RPC_BATCH_ETH_CALL_ERRORS: {str(response_exceptions)}',
                )
                self._logger.trace(
                    'Error in batch_eth_call_on_block_range, error {}', str(exc),
                )
                raise exc
            else:
                response = response_data if isinstance(response_data, list) else [response_data]
                for result in response:
                    rpc_response.append(
                        eth_abi.decode_abi(
                            abi_dict.get(
                                function_name,
                            )['output'],
                            HexBytes(result['result']),
                        ),
                    )

            return rpc_response

        return await f()

    async def batch_eth_get_block(self, from_block, to_block, redis_conn):
        """
        Batch call "eth_getBlockByNumber" in a range of block numbers

        RPC_BATCH: for_each_block -> eth_getBlockByNumber
        """
        if not self._initialized:
            await self.init(redis_conn)

        @retry(
            reraise=True,
            retry=retry_if_exception_type(RPCException),
            wait=wait_random_exponential(multiplier=1, max=10),
            stop=stop_after_attempt(settings.rpc.retry),
            before_sleep=self._on_node_exception,
        )
        async def f():
            rpc_query = []

            request_id = 1
            for block in range(from_block, to_block + 1):
                rpc_query.append(
                    {
                        'jsonrpc': '2.0',
                        'method': 'eth_getBlockByNumber',
                        'params': [
                            hex(block),
                            True,
                        ],
                        'id': request_id,
                    },
                )
                request_id += 1

            node = self.get_current_node()
            rpc_url = node.get('rpc_url')

            await check_rpc_rate_limit(
                parsed_limits=node.get('rate_limit', []),
                app_id=rpc_url.split('/')[-1],
                redis_conn=redis_conn,
                request_payload=rpc_query,
                error_msg={
                    'msg': 'exhausted_api_key_rate_limit inside batch_eth_get_block',
                },
                logger=self._logger,
                rate_limit_lua_script_shas=self._rate_limit_lua_script_shas,
                limit_incr_by=len(rpc_query),
            )
            try:
                response = await self._client.post(url=rpc_url, json=rpc_query)
                response_data = response.json()
            except Exception as e:
                exc = RPCException(
                    request={
                        'from_block': from_block,
                        'to_block': to_block,
                    },
                    response=None,
                    underlying_exception=e,
                    extra_info=f'RPC_BATCH_ETH_CALL_ERROR: {str(e)}',
                )
                self._logger.trace('Error in batch_eth_get_block, error {}', str(exc))
                raise exc

            if response.status_code != 200:
                raise RPCException(
                    request={
                        'from_block': from_block,
                        'to_block': to_block,
                    },
                    response=(response.status_code, response.text),
                    underlying_exception=None,
                    extra_info=f'RPC_BATCH_ETH_CALL_ERROR: {response.text}',
                )
            response_exceptions = list(
                map(
                    lambda r: r,
                    filter(
                        lambda y: type(y) == str or y.get('error', False),
                        response_data,
                    ),
                ),
            )
            if len(response_exceptions) > 0:
                exc = RPCException(
                    request={'from_block': from_block, 'to_block': to_block},
                    response=response_exceptions,
                    underlying_exception=None,
                    extra_info=(
                        f'RPC_BATCH_ETH_GET_BLOCK_ERRORS: {str(response_exceptions)}'
                    ),
                )
                self._logger.trace('Error in batch_eth_get_block, error {}', str(exc))
                raise exc

            return response_data

        return await f()

    async def get_events_logs(
        self, contract_address, to_block, from_block, topics, event_abi, redis_conn,
    ):
        if not self._initialized:
            await self.init(redis_conn)

        @retry(
            reraise=True,
            retry=retry_if_exception_type(RPCException),
            wait=wait_random_exponential(multiplier=1, max=10),
            stop=stop_after_attempt(settings.rpc.retry),
            before_sleep=self._on_node_exception,
        )
        async def f():
            node = self.get_current_node()
            rpc_url = node.get('rpc_url')

            web3_provider = node['web3_client'].w3

            event_log_query = {
                'address': Web3.toChecksumAddress(contract_address),
                'toBlock': to_block,
                'fromBlock': from_block,
                'topics': topics,
            }
            await check_rpc_rate_limit(
                parsed_limits=node.get('rate_limit', []),
                app_id=rpc_url.split('/')[-1],
                redis_conn=redis_conn,
                request_payload=event_log_query,
                error_msg={
                    'msg': 'exhausted_api_key_rate_limit inside get_events_logs',
                },
                logger=self._logger,
                rate_limit_lua_script_shas=self._rate_limit_lua_script_shas,
                limit_incr_by=to_block - from_block + 1,
            )
            try:

                event_log = web3_provider.eth.get_logs(
                    event_log_query,
                )
            except Exception as e:
                exc = RPCException(
                    request={
                        'contract_address': contract_address,
                        'to_block': to_block,
                        'from_block': from_block,
                        'topics': topics,
                    },
                    response=None,
                    underlying_exception=e,
                    extra_info=f'RPC_GET_EVENT_LOGS_ERROR: {str(e)}',
                )
                self._logger.trace('Error in get_events_logs, error {}', str(exc))
                raise exc

            codec: ABICodec = web3_provider.codec
            all_events = []
            for log in event_log:
                abi = event_abi.get(log.topics[0].hex(), '')
                evt = get_event_data(codec, abi, log)
                all_events.append(evt)

            return all_events

        return await f()


rpc_helper = RpcHelper()
