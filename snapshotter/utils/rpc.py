import asyncio
import json
import time
from typing import List
from typing import Union

import eth_abi
import tenacity
from async_limits import parse_many as limit_parse_many
from eth_abi.codec import ABICodec
from eth_utils import keccak
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
from web3._utils.abi import map_abi_data
from web3._utils.events import get_event_data
from web3._utils.normalizers import BASE_RETURN_NORMALIZERS
from web3.eth import AsyncEth
from web3.types import TxParams
from web3.types import Wei

from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import logger
from snapshotter.utils.exceptions import RPCException
from snapshotter.utils.models.settings_model import RPCConfigBase
from snapshotter.utils.redis.rate_limiter import check_rpc_rate_limit
from snapshotter.utils.redis.rate_limiter import load_rate_limiter_scripts
from snapshotter.utils.redis.redis_keys import rpc_blocknumber_calls
from snapshotter.utils.redis.redis_keys import rpc_get_block_number_calls
from snapshotter.utils.redis.redis_keys import rpc_get_event_logs_calls
from snapshotter.utils.redis.redis_keys import rpc_get_transaction_receipt_calls
from snapshotter.utils.redis.redis_keys import rpc_json_rpc_calls
from snapshotter.utils.redis.redis_keys import rpc_web3_calls


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

    def __init__(self, rpc_settings: RPCConfigBase = settings.rpc, archive_mode=False):
        self._archive_mode = archive_mode
        self._rpc_settings = rpc_settings
        self._nodes = list()
        self._current_node_index = 0
        self._node_count = 0
        self._rate_limit_lua_script_shas = None
        self._initialized = False
        self._sync_nodes_initialized = False
        self._logger = logger.bind(module='Powerloom|RpcHelper')
        self._client = None
        self._async_transport = None
        self._rate_limit_lua_script_shas = None

    async def _load_rate_limit_shas(self, redis_conn):
        if self._rate_limit_lua_script_shas is not None:
            return
        self._rate_limit_lua_script_shas = await load_rate_limiter_scripts(
            redis_conn,
        )

    async def _init_http_clients(self):
        if self._client is not None:
            return
        self._async_transport = AsyncHTTPTransport(
            limits=Limits(
                max_connections=self._rpc_settings.connection_limits.max_connections,
                max_keepalive_connections=self._rpc_settings.connection_limits.max_keepalive_connections,
                keepalive_expiry=self._rpc_settings.connection_limits.keepalive_expiry,
            ),
        )
        self._client = AsyncClient(
            timeout=Timeout(timeout=5.0),
            follow_redirects=False,
            transport=self._async_transport,
        )

    async def _load_async_web3_providers(self):
        for node in self._nodes:
            if node['web3_client_async'] is not None:
                continue
            node['web3_client_async'] = Web3(
                Web3.AsyncHTTPProvider(node['rpc_url']),
                modules={'eth': (AsyncEth,)},
                middlewares=[],
            )

    async def init(self, redis_conn):
        if not self._sync_nodes_initialized:
            self._load_web3_providers_and_rate_limits()
            self._sync_nodes_initialized = True
        await self._load_rate_limit_shas(redis_conn)
        await self._init_http_clients()
        await self._load_async_web3_providers()
        self._initialized = True

    def _load_web3_providers_and_rate_limits(self):
        if self._archive_mode:
            nodes = self._rpc_settings.archive_nodes
        else:
            nodes = self._rpc_settings.full_nodes

        for node in nodes:
            try:
                self._nodes.append(
                    {
                        'web3_client': Web3(Web3.HTTPProvider(node.url)),
                        'web3_client_async': None,
                        'rate_limit': limit_parse_many(node.rate_limit),
                        'rpc_url': node.url,
                    },
                )
            except Exception as exc:
                self._logger.opt(exception=settings.logs.trace_enabled).error(
                    (
                        'Error while initialising one of the web3 providers,'
                        f' err_msg: {exc}'
                    ),
                )

        if self._nodes:
            self._node_count = len(self._nodes)

    def get_current_node(self):
        if not self._sync_nodes_initialized:
            self._load_web3_providers_and_rate_limits()
            self._sync_nodes_initialized = True

        if self._node_count == 0:
            raise Exception('No full nodes available')
        return self._nodes[self._current_node_index]

    def _on_node_exception(self, retry_state: tenacity.RetryCallState):
        exc_idx = retry_state.kwargs['node_idx']
        next_node_idx = (retry_state.kwargs.get('node_idx', 0) + 1) % self._node_count
        retry_state.kwargs['node_idx'] = next_node_idx
        self._logger.warning(
            'Found exception while performing RPC {} on node {} at idx {}. '
            'Injecting next node {} at idx {} | exception: {} ',
            retry_state.fn, self._nodes[exc_idx], exc_idx, self._nodes[next_node_idx],
            next_node_idx, retry_state.outcome.exception(),
        )

    async def get_current_block_number(self, redis_conn):
        @retry(
            reraise=True,
            retry=retry_if_exception_type(RPCException),
            wait=wait_random_exponential(multiplier=1, max=10),
            stop=stop_after_attempt(settings.rpc.retry),
            before_sleep=self._on_node_exception,
        )
        async def f(node_idx):
            if not self._initialized:
                await self.init(redis_conn=redis_conn)
            node = self._nodes[node_idx]
            rpc_url = node.get('rpc_url')
            web3_provider = node['web3_client_async']

            await check_rpc_rate_limit(
                parsed_limits=node.get('rate_limit', []),
                app_id=rpc_url.split('/')[-1],
                redis_conn=redis_conn,
                request_payload='get_current_block_number',
                error_msg={
                    'msg': 'exhausted_api_key_rate_limit inside get_current_blocknumber',
                },
                logger=self._logger,
                rate_limit_lua_script_shas=self._rate_limit_lua_script_shas,
                limit_incr_by=1,
            )
            try:
                cur_time = time.time()
                await asyncio.gather(
                    redis_conn.zadd(
                        name=rpc_get_block_number_calls,
                        mapping={
                            json.dumps(
                                'get_current_block_number',
                            ): cur_time,
                        },
                    ),
                    redis_conn.zremrangebyscore(
                        name=rpc_get_block_number_calls,
                        min=0,
                        max=cur_time - 3600,
                    ),
                )
                current_block = await web3_provider.eth.block_number
            except Exception as e:
                exc = RPCException(
                    request='get_current_block_number',
                    response=None,
                    underlying_exception=e,
                    extra_info=f'RPC_GET_CURRENT_BLOCKNUMBER ERROR: {str(e)}',
                )
                self._logger.trace('Error in get_current_block_number, error {}', str(exc))
                raise exc
            else:
                return current_block
        return await f(node_idx=0)

    async def _async_web3_call(self, contract_function, redis_conn, from_address=None):
        """Make async web3 call"""

        @retry(
            reraise=True,
            retry=retry_if_exception_type(RPCException),
            wait=wait_random_exponential(multiplier=1, max=10),
            stop=stop_after_attempt(settings.rpc.retry),
            before_sleep=self._on_node_exception,
        )
        async def f(node_idx):
            try:

                node = self._nodes[node_idx]
                rpc_url = node.get('rpc_url')

                await check_rpc_rate_limit(
                    parsed_limits=node.get('rate_limit', []),
                    app_id=rpc_url.split('/')[-1],
                    redis_conn=redis_conn,
                    request_payload=contract_function.fn_name,
                    error_msg={
                        'msg': 'exhausted_api_key_rate_limit inside web3_call',
                    },
                    logger=self._logger,
                    rate_limit_lua_script_shas=self._rate_limit_lua_script_shas,
                    limit_incr_by=1,
                )

                params: TxParams = {'gas': Wei(0), 'gasPrice': Wei(0)}

                if not contract_function.address:
                    raise ValueError(
                        f'Missing address for batch_call in `{contract_function.fn_name}`',
                    )

                output_type = [
                    output['type'] for output in contract_function.abi['outputs']
                ]
                payload = {
                    'to': contract_function.address,
                    'data': contract_function.build_transaction(params)['data'],
                    'output_type': output_type,
                    'fn_name': contract_function.fn_name,  # For debugging purposes
                }

                cur_time = time.time()
                redis_cache_data = payload.copy()
                redis_cache_data['time'] = cur_time
                await asyncio.gather(
                    redis_conn.zadd(
                        name=rpc_web3_calls,
                        mapping={
                            json.dumps(redis_cache_data): cur_time,
                        },
                    ),
                    redis_conn.zremrangebyscore(
                        name=rpc_web3_calls,
                        min=0,
                        max=cur_time - 3600,
                    ),
                )

                if from_address:
                    payload['from'] = from_address

                data = await node['web3_client_async'].eth.call(payload)

                decoded_data = node['web3_client_async'].codec.decode_abi(
                    output_type, HexBytes(data),
                )

                normalized_data = map_abi_data(
                    BASE_RETURN_NORMALIZERS, output_type, decoded_data,
                )

                if len(normalized_data) == 1:
                    return normalized_data[0]
                else:
                    return normalized_data
            except Exception as e:
                exc = RPCException(
                    request=[contract_function.fn_name],
                    response=None,
                    underlying_exception=e,
                    extra_info={'msg': str(e)},
                )
                self._logger.opt(exception=settings.logs.trace_enabled).error(
                    (
                        'Error while making web3 batch call'
                    ),
                    err=lambda: str(exc),
                )
                raise exc

        return await f(node_idx=0)

    async def get_transaction_receipt(self, tx_hash, redis_conn):
        @retry(
            reraise=True,
            retry=retry_if_exception_type(RPCException),
            wait=wait_random_exponential(multiplier=1, max=10),
            stop=stop_after_attempt(settings.rpc.retry),
            before_sleep=self._on_node_exception,
        )
        async def f(node_idx):
            if not self._initialized:
                await self.init(redis_conn=redis_conn)
            node = self._nodes[node_idx]
            rpc_url = node.get('rpc_url')

            web3_provider = node['web3_client_async']
            tx_receipt_query = {
                'txHash': tx_hash,
            }
            await check_rpc_rate_limit(
                parsed_limits=node.get('rate_limit', []),
                app_id=rpc_url.split('/')[-1],
                redis_conn=redis_conn,
                request_payload=tx_receipt_query,
                error_msg={
                    'msg': 'exhausted_api_key_rate_limit inside get_events_logs',
                },
                logger=self._logger,
                rate_limit_lua_script_shas=self._rate_limit_lua_script_shas,
                limit_incr_by=1,
            )
            try:
                cur_time = time.time()
                await asyncio.gather(
                    redis_conn.zadd(
                        name=rpc_get_transaction_receipt_calls,
                        mapping={
                            json.dumps(
                                tx_receipt_query,
                            ): cur_time,
                        },
                    ),
                    redis_conn.zremrangebyscore(
                        name=rpc_get_transaction_receipt_calls,
                        min=0,
                        max=cur_time - 3600,
                    ),
                )
                tx_receipt_details = await node['web3_client_async'].eth.get_transaction_receipt(
                    tx_hash,
                )
            except Exception as e:
                exc = RPCException(
                    request={
                        'txHash': tx_hash,
                    },
                    response=None,
                    underlying_exception=e,
                    extra_info=f'RPC_GET_TRANSACTION_RECEIPT_ERROR: {str(e)}',
                )
                self._logger.trace('Error in get transaction receipt for tx hash {}, error {}', tx_hash, str(exc))
                raise exc
            else:
                return tx_receipt_details
        return await f(node_idx=0)

    async def get_current_block(self, redis_conn, node_idx=0):
        """Get the current block number.

        Returns:
            int : the current block number
        """
        node = self._nodes[node_idx]
        rpc_url = node.get('rpc_url')

        await check_rpc_rate_limit(
            parsed_limits=node.get('rate_limit', []),
            app_id=rpc_url.split('/')[-1],
            redis_conn=redis_conn,
            request_payload='get_current_block',
            error_msg={
                'msg': 'exhausted_api_key_rate_limit inside web3_call',
            },
            logger=self._logger,
            rate_limit_lua_script_shas=self._rate_limit_lua_script_shas,
            limit_incr_by=1,
        )
        current_block = node['web3_client'].eth.block_number

        cur_time = time.time()
        payload = {'time': cur_time, 'fn_name': 'get_current_block'}
        await asyncio.gather(
            redis_conn.zadd(
                name=rpc_blocknumber_calls,
                mapping={
                    json.dumps(payload): cur_time,
                },
            ),
            redis_conn.zremrangebyscore(
                name=rpc_blocknumber_calls,
                min=0,
                max=cur_time - 3600,
            ),
        )
        return current_block

    async def web3_call(self, tasks, redis_conn, from_address=None):
        """
        Call web3 functions in parallel
        """
        if not self._initialized:
            await self.init(redis_conn)

        try:
            web3_tasks = [
                self._async_web3_call(
                    contract_function=task, redis_conn=redis_conn, from_address=from_address,
                ) for task in tasks
            ]
            response = await asyncio.gather(*web3_tasks)
            return response
        except Exception as e:
            raise e

    async def _make_rpc_jsonrpc_call(self, rpc_query, redis_conn):
        """Make a jsonrpc call to the given rpc_url"""

        @retry(
            reraise=True,
            retry=retry_if_exception_type(RPCException),
            wait=wait_random_exponential(multiplier=1, max=10),
            stop=stop_after_attempt(settings.rpc.retry),
            before_sleep=self._on_node_exception,
        )
        async def f(node_idx):

            node = self._nodes[node_idx]
            rpc_url = node.get('rpc_url')

            await check_rpc_rate_limit(
                parsed_limits=node.get('rate_limit', []),
                app_id=rpc_url.split('/')[-1],
                redis_conn=redis_conn,
                request_payload=rpc_query,
                error_msg={
                    'msg': 'exhausted_api_key_rate_limit inside make_rpc_jsonrpc_call',
                },
                logger=self._logger,
                rate_limit_lua_script_shas=self._rate_limit_lua_script_shas,
                limit_incr_by=1,
            )

            try:
                cur_time = time.time()
                await asyncio.gather(
                    redis_conn.zadd(
                        name=rpc_json_rpc_calls,
                        mapping={json.dumps(rpc_query): cur_time},
                    ),
                    redis_conn.zremrangebyscore(
                        name=rpc_json_rpc_calls,
                        min=0,
                        max=cur_time - 3600,
                    ),
                )
                response = await self._client.post(url=rpc_url, json=rpc_query)
                response_data = response.json()
            except Exception as e:
                exc = RPCException(
                    request=rpc_query,
                    response=None,
                    underlying_exception=e,
                    extra_info=f'RPC_BATCH_ETH_CALL_ERROR: {str(e)}',
                )
                self._logger.trace(
                    'Error in making jsonrpc call, error {}', str(exc),
                )
                raise exc

            if response.status_code != 200:
                raise RPCException(
                    request=rpc_query,
                    response=(response.status_code, response.text),
                    underlying_exception=None,
                    extra_info=f'RPC_CALL_ERROR: {response.text}',
                )

            response_exceptions = []
            if type(response_data) is list:
                for response_item in response_data:
                    if 'error' in response_item:
                        response_exceptions.append(
                            response_exceptions.append(response_item['error']),
                        )
            else:
                if 'error' in response_data:
                    response_exceptions.append(response_data['error'])

            if response_exceptions:
                raise RPCException(
                    request=rpc_query,
                    response=response_data,
                    underlying_exception=response_exceptions,
                    extra_info=f'RPC_BATCH_ETH_CALL_ERROR: {response_exceptions}',
                )

            return response_data
        return await f(node_idx=0)

    async def batch_eth_get_balance_on_block_range(
            self,
            address,
            redis_conn,
            from_block,
            to_block,
    ):
        """
        Batch call eth_getBalance for given block-range

        RPC_BATCH: for_each_block -> eth_getBalance
        """
        if not self._initialized:
            await self.init(redis_conn)

        rpc_query = []
        request_id = 1
        for block in range(from_block, to_block + 1):
            rpc_query.append(
                {
                    'jsonrpc': '2.0',
                    'method': 'eth_getBalance',
                    'params': [address, hex(block)],
                    'id': request_id,
                },
            )
            request_id += 1

        try:
            response_data = await self._make_rpc_jsonrpc_call(rpc_query, redis_conn)

            rpc_respnse = []

            for response in response_data:
                if 'result' in response:
                    eth_balance = response['result']
                    rpc_respnse.append(eth_balance)
                else:
                    rpc_respnse.append(None)

            return rpc_respnse

        except Exception as e:
            raise e

    async def batch_eth_call_on_block_range(
        self,
        abi_dict,
        function_name,
        contract_address,
        redis_conn,
        from_block,
        to_block,
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

        function_signature = get_encoded_function_signature(
            abi_dict, function_name, params,
        )
        rpc_query = []
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

        response_data = await self._make_rpc_jsonrpc_call(rpc_query, redis_conn=redis_conn)
        rpc_response = []

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

    async def batch_eth_get_block(self, from_block, to_block, redis_conn):
        """
        Batch call "eth_getBlockByNumber" in a range of block numbers

        RPC_BATCH: for_each_block -> eth_getBlockByNumber
        """
        if not self._initialized:
            await self.init(redis_conn)

        rpc_query = []

        request_id = 1
        for block in range(from_block, to_block + 1):
            rpc_query.append(
                {
                    'jsonrpc': '2.0',
                    'method': 'eth_getBlockByNumber',
                    'params': [
                        hex(block),
                        False,
                    ],
                    'id': request_id,
                },
            )
            request_id += 1

        response_data = await self._make_rpc_jsonrpc_call(rpc_query, redis_conn=redis_conn)
        return response_data

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
        async def f(node_idx):
            node = self._nodes[node_idx]
            rpc_url = node.get('rpc_url')

            web3_provider = node['web3_client_async']

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
                limit_incr_by=1,
            )
            try:
                cur_time = time.time()
                await asyncio.gather(
                    redis_conn.zadd(
                        name=rpc_get_event_logs_calls,
                        mapping={
                            json.dumps(
                                event_log_query,
                            ): cur_time,
                        },
                    ),
                    redis_conn.zremrangebyscore(
                        name=rpc_get_event_logs_calls,
                        min=0,
                        max=cur_time - 3600,
                    ),
                )

                event_log = await web3_provider.eth.get_logs(
                    event_log_query,
                )
                codec: ABICodec = web3_provider.codec
                all_events = []
                for log in event_log:
                    abi = event_abi.get(log.topics[0].hex(), '')
                    evt = get_event_data(codec, abi, log)
                    all_events.append(evt)

                return all_events
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

        return await f(node_idx=0)
