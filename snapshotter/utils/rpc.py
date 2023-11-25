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
    Returns a dictionary of function signatures, inputs, outputs and full ABI for a given contract ABI.

    Args:
        abi (list): List of dictionaries representing the contract ABI.

    Returns:
        dict: Dictionary containing function signatures, inputs, outputs and full ABI.
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
    Returns the encoded function signature for a given function name and parameters.

    Args:
        abi_dict (dict): The ABI dictionary for the contract.
        function_name (str): The name of the function.
        params (list or None): The list of parameters for the function.

    Returns:
        str: The encoded function signature.
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
    """
    Given a dictionary of event signatures and a dictionary of event ABIs,
    returns a tuple containing a list of event signatures and a dictionary of
    event ABIs keyed by their corresponding signature hash.
    """
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
        """
        Initializes an instance of the RpcHelper class.

        Args:
            rpc_settings (RPCConfigBase, optional): The RPC configuration settings to use. Defaults to settings.rpc.
            archive_mode (bool, optional): Whether to operate in archive mode. Defaults to False.
        """
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
        """
        Loads the rate limit Lua script SHA values from Redis if they haven't already been loaded.

        Args:
            redis_conn: Redis connection object.

        Returns:
            None
        """

        if self._rate_limit_lua_script_shas is not None:
            return
        self._rate_limit_lua_script_shas = await load_rate_limiter_scripts(
            redis_conn,
        )

    async def _init_http_clients(self):
        """
        Initializes the HTTP clients for making RPC requests.

        If the client has already been initialized, this function returns immediately.

        :return: None
        """
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
        """
        Loads async web3 providers for each node in the list of nodes.
        If a node already has a web3 client, it is skipped.
        """
        for node in self._nodes:
            if node['web3_client_async'] is not None:
                continue
            node['web3_client_async'] = Web3(
                Web3.AsyncHTTPProvider(node['rpc_url']),
                modules={'eth': (AsyncEth,)},
                middlewares=[],
            )

    async def init(self, redis_conn):
        """
        Initializes the RPC client by loading web3 providers and rate limits,
        loading rate limit SHAs, initializing HTTP clients, and loading async
        web3 providers.

        Args:
            redis_conn: Redis connection object.

        Returns:
            None
        """
        if not self._sync_nodes_initialized:
            self._load_web3_providers_and_rate_limits()
            self._sync_nodes_initialized = True
        await self._load_rate_limit_shas(redis_conn)
        await self._init_http_clients()
        await self._load_async_web3_providers()
        self._initialized = True

    def _load_web3_providers_and_rate_limits(self):
        """
        Load web3 providers and rate limits based on the archive mode.
        If archive mode is True, load archive nodes, otherwise load full nodes.
        """
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
        """
        Returns the current node to use for RPC calls.

        If the sync nodes have not been initialized, it initializes them by loading web3 providers and rate limits.
        If there are no full nodes available, it raises an exception.

        Returns:
            The current node to use for RPC calls.
        """
        if not self._sync_nodes_initialized:
            self._load_web3_providers_and_rate_limits()
            self._sync_nodes_initialized = True

        if self._node_count == 0:
            raise Exception('No full nodes available')
        return self._nodes[self._current_node_index]

    def _on_node_exception(self, retry_state: tenacity.RetryCallState):
        """
        Callback function to handle exceptions raised during RPC calls to nodes.
        It updates the node index to retry the RPC call on the next node.

        Args:
            retry_state (tenacity.RetryCallState): The retry state object containing information about the retry.

        Returns:
            None
        """
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
        """
        Returns the current block number of the Ethereum blockchain.

        Args:
            redis_conn: Redis connection object.

        Returns:
            The current block number of the Ethereum blockchain.

        Raises:
            RPCException: If an error occurs while making the RPC call.
        """
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
        """
        Executes a web3 call asynchronously.

        Args:
            contract_function: The contract function to call.
            redis_conn: The Redis connection object.
            from_address: The address to send the transaction from.

        Returns:
            The result of the web3 call.
        """
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
        """
        Retrieves the transaction receipt for a given transaction hash.

        Args:
            tx_hash (str): The transaction hash for which to retrieve the receipt.
            redis_conn: Redis connection object.

        Returns:
            The transaction receipt details as a dictionary.

        Raises:
            RPCException: If an error occurs while retrieving the transaction receipt.
        """

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
        """
        Returns the current block number from the Ethereum node at the specified index.

        Args:
            redis_conn (redis.Redis): Redis connection object.
            node_idx (int): Index of the Ethereum node to use. Defaults to 0.

        Returns:
            int: The current block number.

        Raises:
            ExhaustedApiKeyRateLimitError: If the API key rate limit for the node is exhausted.
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
        Calls the given tasks asynchronously using web3 and returns the response.

        Args:
            tasks (list): List of contract functions to call.
            redis_conn: Redis connection object.
            from_address (str, optional): Address to use as the transaction sender. Defaults to None.

        Returns:
            list: List of responses from the contract function calls.
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
        """
        Makes an RPC JSON-RPC call to a node in the pool.

        Args:
            rpc_query (dict): The JSON-RPC query to be sent.
            redis_conn (Redis): The Redis connection object.

        Returns:
            dict: The JSON-RPC response data.

        Raises:
            RPCException: If there is an error in making the JSON-RPC call.
        """
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
        Batch retrieves the Ethereum balance of an address for a range of blocks.

        Args:
            address (str): The Ethereum address to retrieve the balance for.
            redis_conn (redis.Redis): The Redis connection object.
            from_block (int): The starting block number.
            to_block (int): The ending block number.

        Returns:
            list: A list of Ethereum balances for each block in the range. If a balance could not be retrieved for a block,
            None is returned in its place.
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
        Batch executes an Ethereum contract function call on a range of blocks.

        Args:
            abi_dict (dict): The ABI dictionary of the contract.
            function_name (str): The name of the function to call.
            contract_address (str): The address of the contract.
            redis_conn (redis.Redis): The Redis connection object.
            from_block (int): The starting block number.
            to_block (int): The ending block number.
            params (list, optional): The list of parameters to pass to the function. Defaults to None.
            from_address (str, optional): The address to use as the sender of the transaction. Defaults to '0x0000000000000000000000000000000000000000'.

        Returns:
            list: A list of decoded results from the function call.
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
        Batch retrieves Ethereum blocks using eth_getBlockByNumber JSON-RPC method.

        Args:
            from_block (int): The block number to start retrieving from.
            to_block (int): The block number to stop retrieving at.
            redis_conn (redis.Redis): Redis connection object.

        Returns:
            dict: A dictionary containing the response data from the JSON-RPC call.
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
        """
        Returns all events logs for a given contract address, within a specified block range and with specified topics.

        Args:
            contract_address (str): The address of the contract to get events logs for.
            to_block (int): The highest block number to retrieve events logs from.
            from_block (int): The lowest block number to retrieve events logs from.
            topics (List[str]): A list of topics to filter the events logs by.
            event_abi (Dict): The ABI of the event to decode the logs with.
            redis_conn (Redis): The Redis connection object to use for rate limiting.

        Returns:
            List[Dict]: A list of dictionaries representing the decoded events logs.
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
