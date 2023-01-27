import asyncio
import json
from functools import partial

from redis import asyncio as aioredis
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential
from web3 import Web3

from pooler.callback_modules.uniswap.constants import global_w3_client
from pooler.callback_modules.uniswap.constants import pair_contract_abi
from pooler.callback_modules.uniswap.constants import UNISWAP_EVENTS_ABI
from pooler.callback_modules.uniswap.constants import UNISWAP_TRADE_EVENT_SIGS
from pooler.callback_modules.uniswap.helpers import get_block_details_in_block_range
from pooler.callback_modules.uniswap.helpers import get_pair_metadata
from pooler.callback_modules.uniswap.pricing import get_eth_price_usd
from pooler.callback_modules.uniswap.pricing import get_token_price_in_block_range
from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.models.data_models import epoch_event_trade_data
from pooler.utils.models.data_models import event_trade_data
from pooler.utils.models.data_models import trade_data
from pooler.utils.redis.rate_limiter import check_rpc_rate_limit
from pooler.utils.redis.rate_limiter import load_rate_limiter_scripts
from pooler.utils.redis.redis_conn import provide_async_redis_conn_insta
from pooler.utils.rpc_helper import batch_eth_call_on_block_range
from pooler.utils.rpc_helper import contract_abi_dict
from pooler.utils.rpc_helper import get_event_sig_and_abi
from pooler.utils.rpc_helper import get_events_logs
from pooler.utils.rpc_helper import inject_web3_provider_first_run
from pooler.utils.rpc_helper import inject_web3_provider_on_exception
from pooler.utils.rpc_helper import RPCException

core_logger = logger.bind(module='PowerLoom|UniswapCore')


@provide_async_redis_conn_insta
@inject_web3_provider_first_run
@retry(
    reraise=True,
    retry=retry_if_exception_type(RPCException),
    wait=wait_random_exponential(multiplier=1, max=10),
    stop=stop_after_attempt(settings.uniswap_functions.retrial_attempts),
    before_sleep=inject_web3_provider_on_exception,
)
async def get_pair_reserves(
    loop: asyncio.AbstractEventLoop,
    rate_limit_lua_script_shas: dict,
    pair_address, from_block, to_block,
    redis_conn: aioredis.Redis = None,
    fetch_timestamp=False,
    web3_provider=global_w3_client,
):
    try:
        core_logger.debug(f'Starting pair total reserves query for: {pair_address}')
        if not rate_limit_lua_script_shas:
            rate_limit_lua_script_shas = await load_rate_limiter_scripts(redis_conn)
        pair_address = Web3.toChecksumAddress(pair_address)

        if fetch_timestamp:
            try:
                block_details_dict = await get_block_details_in_block_range(
                    from_block, to_block, redis_conn=redis_conn,
                    rate_limit_lua_script_shas=rate_limit_lua_script_shas, web3_provider=web3_provider,
                )
            except Exception as err:
                core_logger.opt(exception=True).error(
                    'Error attempting to get block details of block-range {}-{}: {}, retrying again',
                    from_block, to_block, err,
                )
                raise err
        else:
            block_details_dict = dict()

        pair_per_token_metadata = await get_pair_metadata(
            pair_address=pair_address, loop=loop, redis_conn=redis_conn,
            rate_limit_lua_script_shas=rate_limit_lua_script_shas,
        )

        core_logger.debug(
            f'total pair reserves fetched block details for epoch for: {pair_address}',
        )

        token0_price_map, token1_price_map = await asyncio.gather(
            get_token_price_in_block_range(
                token_metadata=pair_per_token_metadata['token0'], from_block=from_block, to_block=to_block, loop=loop,
                redis_conn=redis_conn, rate_limit_lua_script_shas=rate_limit_lua_script_shas, debug_log=False, web3_provider=web3_provider,
            ),
            get_token_price_in_block_range(
                token_metadata=pair_per_token_metadata['token1'], from_block=from_block, to_block=to_block, loop=loop,
                redis_conn=redis_conn, rate_limit_lua_script_shas=rate_limit_lua_script_shas, debug_log=False, web3_provider=web3_provider,
            ),
        )

        core_logger.debug(f'Total reserves fetched token prices for: {pair_address}')

        # create dictionary of ABI {function_name -> {signature, abi, input, output}}
        pair_abi_dict = contract_abi_dict(pair_contract_abi)
        # get token price function takes care of its own rate limit
        await check_rpc_rate_limit(
            parsed_limits=web3_provider.get('rate_limit', []), app_id=web3_provider.get('rpc_url').split('/')[-1], redis_conn=redis_conn,
            request_payload={
                'contract': pair_address,
                'from_block': from_block, 'to_block': to_block,
            },
            error_msg={'msg': 'exhausted_api_key_rate_limit inside get_pair_reserves'},
            logger=core_logger, rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1,
        )
        reserves_array = batch_eth_call_on_block_range(
            rpc_endpoint=web3_provider.get('rpc_url'), abi_dict=pair_abi_dict, function_name='getReserves',
            contract_address=pair_address, from_block=from_block, to_block=to_block,
        )
        if not reserves_array:
            raise RPCException(
                request={
                    'contract': pair_address,
                    'from_block': from_block, 'to_block': to_block,
                },
                response=reserves_array, underlying_exception=None,
                extra_info={'msg': f'Error: failed to retrieve pair reserves from RPC'},
            )

        core_logger.debug(f'Total reserves fetched getReserves results: {pair_address}')
        token0_decimals = pair_per_token_metadata['token0']['decimals']
        token1_decimals = pair_per_token_metadata['token1']['decimals']

        pair_reserves_arr = dict()
        block_count = 0
        for block_num in range(from_block, to_block + 1):
            token0Amount = reserves_array[block_count][0] / \
                10 ** int(token0_decimals) if reserves_array[block_count][0] else 0
            token1Amount = reserves_array[block_count][1] / \
                10 ** int(token1_decimals) if reserves_array[block_count][1] else 0

            token0USD = token0Amount * token0_price_map.get(block_num, 0)
            token1USD = token1Amount * token1_price_map.get(block_num, 0)

            current_block_details = block_details_dict.get(block_num, None)
            timestamp = current_block_details.get(
                'timestamp', None,
            ) if current_block_details else None

            pair_reserves_arr[block_num] = {
                'token0': token0Amount,
                'token1': token1Amount,
                'token0USD': token0USD,
                'token1USD': token1USD,
                'timestamp': timestamp,
            }
            block_count += 1

        core_logger.debug(
            f'Calculated pair total reserves for epoch-range: {from_block} - {to_block} | pair_contract: {pair_address}',
        )
        return pair_reserves_arr
    except Exception as exc:
        core_logger.opt(exception=True).error(
            'error at get_pair_reserves fn, retrying..., error_msg: {}',
        )
        raise RPCException(
            request={'contract': pair_address, 'from_block': from_block, 'to_block': to_block},
            response={}, underlying_exception=None,
            extra_info={'msg': f'Error: get_pair_reserves error_msg: {str(exc)}'},
        ) from exc


def extract_trade_volume_log(event_name, log, pair_per_token_metadata, token0_price_map, token1_price_map, block_details_dict):
    token0_amount = 0
    token1_amount = 0
    token0_amount_usd = 0
    token1_amount_usd = 0

    def token_native_and_usd_amount(token, token_type, token_price_map):
        if log.args.get(token_type) <= 0:
            return 0, 0

        token_amount = log.args.get(token_type) / \
            10 ** int(pair_per_token_metadata[token]['decimals'])
        token_usd_amount = token_amount * token_price_map.get(log.get('blockNumber'), 0)
        return token_amount, token_usd_amount

    if event_name == 'Swap':

        amount0In, amount0In_usd = token_native_and_usd_amount(
            token='token0', token_type='amount0In', token_price_map=token0_price_map,
        )
        amount0Out, amount0Out_usd = token_native_and_usd_amount(
            token='token0', token_type='amount0Out', token_price_map=token0_price_map,
        )
        amount1In, amount1In_usd = token_native_and_usd_amount(
            token='token1', token_type='amount1In', token_price_map=token1_price_map,
        )
        amount1Out, amount1Out_usd = token_native_and_usd_amount(
            token='token1', token_type='amount1Out', token_price_map=token1_price_map,
        )

        token0_amount = abs(amount0Out - amount0In)
        token1_amount = abs(amount1Out - amount1In)

        token0_amount_usd = abs(amount0Out_usd - amount0In_usd)
        token1_amount_usd = abs(amount1Out_usd - amount1In_usd)

    elif event_name == 'Mint' or event_name == 'Burn':
        token0_amount, token0_amount_usd = token_native_and_usd_amount(
            token='token0', token_type='amount0', token_price_map=token0_price_map,
        )
        token1_amount, token1_amount_usd = token_native_and_usd_amount(
            token='token1', token_type='amount1', token_price_map=token1_price_map,
        )

    trade_volume_usd = 0
    trade_fee_usd = 0

    block_details = block_details_dict.get(int(log.get('blockNumber', 0)), {})
    log = json.loads(Web3.toJSON(log))
    log['token0_amount'] = token0_amount
    log['token1_amount'] = token1_amount
    log['timestamp'] = block_details.get('timestamp', '')
    # pop unused log props
    log.pop('blockHash', None)
    log.pop('transactionIndex', None)

    # if event is 'Swap' then only add single token in total volume calculation
    if event_name == 'Swap':

        # set one side token value in swap case
        if token1_amount_usd and token0_amount_usd:
            trade_volume_usd = token1_amount_usd if token1_amount_usd > token0_amount_usd else token0_amount_usd
        else:
            trade_volume_usd = token1_amount_usd if token1_amount_usd else token0_amount_usd

        # calculate uniswap LP fee
        trade_fee_usd = token1_amount_usd * \
            0.003 if token1_amount_usd else token0_amount_usd * 0.003  # uniswap LP fee rate

        # set final usd amount for swap
        log['trade_amount_usd'] = trade_volume_usd

        return trade_data(
            totalTradesUSD=trade_volume_usd,
            totalFeeUSD=trade_fee_usd,
            token0TradeVolume=token0_amount,
            token1TradeVolume=token1_amount,
            token0TradeVolumeUSD=token0_amount_usd,
            token1TradeVolumeUSD=token1_amount_usd,
        ), log

    trade_volume_usd = token0_amount_usd + token1_amount_usd

    # set final usd amount for other events
    log['trade_amount_usd'] = trade_volume_usd

    return trade_data(
        totalTradesUSD=trade_volume_usd,
        totalFeeUSD=0.0,
        token0TradeVolume=token0_amount,
        token1TradeVolume=token1_amount,
        token0TradeVolumeUSD=token0_amount_usd,
        token1TradeVolumeUSD=token1_amount_usd,
    ), log


# asynchronously get trades on a pair contract
@provide_async_redis_conn_insta
@inject_web3_provider_first_run
@retry(
    reraise=True,
    retry=retry_if_exception_type(RPCException),
    wait=wait_random_exponential(multiplier=1, max=10),
    stop=stop_after_attempt(settings.uniswap_functions.retrial_attempts),
    before_sleep=inject_web3_provider_on_exception,
)
async def get_pair_trade_volume(
    rate_limit_lua_script_shas: dict,
    data_source_contract_address,
    min_chain_height,
    max_chain_height,
    redis_conn: aioredis.Redis = None,
    fetch_timestamp=True,
    web3_provider=global_w3_client,
):
    try:
        ev_loop = asyncio.get_running_loop()

        data_source_contract_address = Web3.toChecksumAddress(data_source_contract_address)
        block_details_dict = dict()

        if fetch_timestamp:
            try:
                block_details_dict = await get_block_details_in_block_range(
                    redis_conn=redis_conn, from_block=min_chain_height,
                    to_block=max_chain_height, rate_limit_lua_script_shas=rate_limit_lua_script_shas,
                    web3_provider=web3_provider,
                )
            except Exception as err:
                core_logger.opt(exception=True).error(
                    'Error attempting to get block details of to_block {}: {}, retrying again', max_chain_height, err,
                )
                raise err

        pair_per_token_metadata = await get_pair_metadata(
            pair_address=data_source_contract_address,
            loop=ev_loop,
            redis_conn=redis_conn,
            rate_limit_lua_script_shas=rate_limit_lua_script_shas,
        )
        token0_price_map, token1_price_map = await asyncio.gather(
            get_token_price_in_block_range(
                token_metadata=pair_per_token_metadata[
                    'token0'
                ], from_block=min_chain_height, to_block=max_chain_height, web3_provider=web3_provider,
                loop=ev_loop, redis_conn=redis_conn, rate_limit_lua_script_shas=rate_limit_lua_script_shas, debug_log=False,
            ),
            get_token_price_in_block_range(
                token_metadata=pair_per_token_metadata[
                    'token1'
                ], from_block=min_chain_height, to_block=max_chain_height, web3_provider=web3_provider,
                loop=ev_loop, redis_conn=redis_conn, rate_limit_lua_script_shas=rate_limit_lua_script_shas, debug_log=False,
            ),
        )

        # fetch logs for swap, mint & burn
        event_sig, event_abi = get_event_sig_and_abi(
            UNISWAP_TRADE_EVENT_SIGS, UNISWAP_EVENTS_ABI,
        )
        pfunc_get_event_logs = partial(
            get_events_logs, **{
                'web3Provider': web3_provider['web3_client'].w3,
                'contract_address': data_source_contract_address,
                'toBlock': max_chain_height,
                'fromBlock': min_chain_height,
                'topics': [event_sig],
                'event_abi': event_abi,
            },
        )
        await check_rpc_rate_limit(
            parsed_limits=web3_provider.get('rate_limit', []), app_id=web3_provider.get('rpc_url').split('/')[-1], redis_conn=redis_conn,
            request_payload={
                'contract': data_source_contract_address,
                'to_block': max_chain_height, 'from_block': min_chain_height,
            },
            error_msg={
                'msg': 'exhausted_api_key_rate_limit inside uniswap_functions get async trade volume',
            },
            logger=core_logger, rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1,
        )
        events_log = await ev_loop.run_in_executor(func=pfunc_get_event_logs, executor=None)

        # group logs by txHashs ==> {txHash: [logs], ...}
        grouped_by_tx = dict()
        [
            grouped_by_tx[log.transactionHash.hex()].append(log) if log.transactionHash.hex(
            ) in grouped_by_tx else grouped_by_tx.update({log.transactionHash.hex(): [log]}) for log in events_log
        ]

        # init data models with empty/0 values
        epoch_results = epoch_event_trade_data(
            Swap=event_trade_data(
                logs=[], trades=trade_data(
                    totalTradesUSD=float(),
                    totalFeeUSD=float(),
                    token0TradeVolume=float(),
                    token1TradeVolume=float(),
                    token0TradeVolumeUSD=float(),
                    token1TradeVolumeUSD=float(),
                    recent_transaction_logs=list(),
                ),
            ),
            Mint=event_trade_data(
                logs=[], trades=trade_data(
                    totalTradesUSD=float(),
                    totalFeeUSD=float(),
                    token0TradeVolume=float(),
                    token1TradeVolume=float(),
                    token0TradeVolumeUSD=float(),
                    token1TradeVolumeUSD=float(),
                    recent_transaction_logs=list(),
                ),
            ),
            Burn=event_trade_data(
                logs=[], trades=trade_data(
                    totalTradesUSD=float(),
                    totalFeeUSD=float(),
                    token0TradeVolume=float(),
                    token1TradeVolume=float(),
                    token0TradeVolumeUSD=float(),
                    token1TradeVolumeUSD=float(),
                    recent_transaction_logs=list(),
                ),
            ),
            Trades=trade_data(
                totalTradesUSD=float(),
                totalFeeUSD=float(),
                token0TradeVolume=float(),
                token1TradeVolume=float(),
                token0TradeVolumeUSD=float(),
                token1TradeVolumeUSD=float(),
                recent_transaction_logs=list(),
            ),
        )

        # prepare final trade logs structure
        for tx_hash, logs in grouped_by_tx.items():

            # init temporary trade object to track trades at txHash level
            tx_hash_trades = trade_data(
                totalTradesUSD=float(),
                totalFeeUSD=float(),
                token0TradeVolume=float(),
                token1TradeVolume=float(),
                token0TradeVolumeUSD=float(),
                token1TradeVolumeUSD=float(),
                recent_transaction_logs=list(),
            )
            # shift Burn logs in end of list to check if equal size of mint already exist and then cancel out burn with mint
            logs = sorted(logs, key=lambda x: x.event, reverse=True)

            # iterate over each txHash logs
            for log in logs:
                # fetch trade value fog log
                trades_result, processed_log = extract_trade_volume_log(
                    event_name=log.event,
                    log=log,
                    pair_per_token_metadata=pair_per_token_metadata,
                    token0_price_map=token0_price_map,
                    token1_price_map=token1_price_map,
                    block_details_dict=block_details_dict,
                )

                if log.event == 'Swap':
                    epoch_results.Swap.logs.append(processed_log)
                    epoch_results.Swap.trades += trades_result
                    tx_hash_trades += trades_result  # swap in single txHash should be added

                elif log.event == 'Mint':
                    epoch_results.Mint.logs.append(processed_log)
                    epoch_results.Mint.trades += trades_result

                elif log.event == 'Burn':
                    epoch_results.Burn.logs.append(processed_log)
                    epoch_results.Burn.trades += trades_result

            # At the end of txHash logs we must normalize trade values, so it don't affect result of other txHash logs
            epoch_results.Trades += abs(tx_hash_trades)
        epoch_trade_logs = epoch_results.dict()
        max_block_details = block_details_dict.get(max_chain_height, {})
        max_block_timestamp = max_block_details.get('timestamp', None)
        epoch_trade_logs.update({'timestamp': max_block_timestamp})
        return epoch_trade_logs
    except Exception as exc:
        core_logger.opt(exception=True).error('error at get_pair_trade_volume fn: {}', exc)
        raise RPCException(
            request={
                'contract': data_source_contract_address,
                'fromBlock': min_chain_height, 'toBlock': max_chain_height,
            },
            response={}, underlying_exception=None,
            extra_info={'msg': f'error: get_pair_trade_volume, error_msg: {str(exc)}'},
        ) from exc


async def warm_up_cache_for_snapshot_constructors(
    loop: asyncio.AbstractEventLoop,
    from_block, to_block,
    rate_limit_lua_script_shas=None,
    redis_conn: aioredis.Redis = None,
    web3_provider=global_w3_client,
):
    """
    This function warm-up cache for uniswap helper functions. Generated cache will be used across
    snapshot constructors or in multiple pair-contract calculations.
    : cache block details for epoch
    : cache ETH USD price for epoch
    """
    await asyncio.gather(
        get_eth_price_usd(
            loop=loop, from_block=from_block, to_block=to_block,
            web3_provider=web3_provider,
        ),
        get_block_details_in_block_range(
            from_block=from_block, to_block=to_block,
            web3_provider=web3_provider,
        ),
        return_exceptions=True,
    )

    return None
