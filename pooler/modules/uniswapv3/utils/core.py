import asyncio
import json

from redis import asyncio as aioredis
from web3 import Web3

from .constants import pair_contract_abi
from .constants import UNISWAP_EVENTS_ABI
from .constants import UNISWAP_TRADE_EVENT_SIGS
from .helpers import get_pair_metadata
from .helpers import transform_tick_bytes_to_tvl
from .models.data_models import epoch_event_trade_data
from .models.data_models import event_trade_data
from .models.data_models import trade_data
from .pricing import (
    get_token_price_in_block_range,
)
from pooler.utils.default_logger import logger
from pooler.utils.rpc import get_contract_abi_dict
from pooler.utils.rpc import get_event_sig_and_abi
from pooler.utils.rpc import RpcHelper
from pooler.utils.snapshot_utils import (
    get_block_details_in_block_range,
)

core_logger = logger.bind(module='PowerLoom|UniswapCore')


async def get_pair_reserves(
    pair_address,
    from_block,
    to_block,
    redis_conn: aioredis.Redis,
    rpc_helper: RpcHelper,
    fetch_timestamp=False,
):
    core_logger.debug(
        f'Starting pair total reserves query for: {pair_address}',
    )
    pair_address = Web3.toChecksumAddress(pair_address)

    if fetch_timestamp:
        try:
            block_details_dict = await get_block_details_in_block_range(
                from_block,
                to_block,
                redis_conn=redis_conn,
                rpc_helper=rpc_helper,
            )
        except Exception as err:
            core_logger.opt(exception=True).error(
                (
                    'Error attempting to get block details of block-range'
                    ' {}-{}: {}, retrying again'
                ),
                from_block,
                to_block,
                err,
            )
            raise err
    else:
        block_details_dict = dict()

    pair_per_token_metadata = await get_pair_metadata(
        pair_address=pair_address,
        redis_conn=redis_conn,
        rpc_helper=rpc_helper,
    )

    core_logger.debug(
        (
            'total pair reserves fetched block details for epoch for:'
            f' {pair_address}'
        ),
    )

    token0_price_map, token1_price_map = await asyncio.gather(
        get_token_price_in_block_range(
            token_metadata=pair_per_token_metadata['token0'],
            from_block=from_block,
            to_block=to_block,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
            debug_log=False,
        ),
        get_token_price_in_block_range(
            token_metadata=pair_per_token_metadata['token1'],
            from_block=from_block,
            to_block=to_block,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
            debug_log=False,
        ),
    )

    core_logger.debug(
        f'Total reserves fetched token prices for: {pair_address}',
    )

    # create dictionary of ABI {function_name -> {signature, abi, input, output}}
    pair_abi_dict = get_contract_abi_dict(pair_contract_abi)
    # get token price function takes care of its own rate limit

    reserves_array = await rpc_helper.batch_eth_call_on_block_range(
        abi_dict=pair_abi_dict,
        function_name='getReserves',
        contract_address=pair_address,
        from_block=from_block,
        to_block=to_block,
        redis_conn=redis_conn,
    )

    core_logger.debug(
        f'Total reserves fetched getReserves results: {pair_address}',
    )
    token0_decimals = pair_per_token_metadata['token0']['decimals']
    token1_decimals = pair_per_token_metadata['token1']['decimals']

    pair_reserves_arr = dict()
    block_count = 0
    for block_num in range(from_block, to_block + 1):
        token0Amount = (
            reserves_array[block_count][0] / 10 ** int(token0_decimals)
            if reserves_array[block_count][0]
            else 0
        )
        token1Amount = (
            reserves_array[block_count][1] / 10 ** int(token1_decimals)
            if reserves_array[block_count][1]
            else 0
        )

        token0USD = token0Amount * token0_price_map.get(block_num, 0)
        token1USD = token1Amount * token1_price_map.get(block_num, 0)

        token0Price = token0_price_map.get(block_num, 0)
        token1Price = token1_price_map.get(block_num, 0)

        current_block_details = block_details_dict.get(block_num, None)
        timestamp = (
            current_block_details.get(
                'timestamp',
                None,
            )
            if current_block_details
            else None
        )

        pair_reserves_arr[block_num] = {
            'token0': token0Amount,
            'token1': token1Amount,
            'token0USD': token0USD,
            'token1USD': token1USD,
            'token0Price': token0Price,
            'token1Price': token1Price,
            'timestamp': timestamp,
        }
        block_count += 1

    core_logger.debug(
        (
            'Calculated pair total reserves for epoch-range:'
            f' {from_block} - {to_block} | pair_contract: {pair_address}'
        ),
    )
    return pair_reserves_arr


def extract_trade_volume_log(
    event_name,
    log,
    pair_per_token_metadata,
    token0_price_map,
    token1_price_map,
    block_details_dict,
):
    token0_amount = 0
    token1_amount = 0
    token0_amount_usd = 0
    token1_amount_usd = 0

    def token_native_and_usd_amount(token, token_type, token_price_map):
        if log.args.get(token_type) <= 0:
            return 0, 0

        token_amount = log.args.get(token_type) / 10 ** int(
            pair_per_token_metadata[token]['decimals'],
        )
        token_usd_amount = token_amount * token_price_map.get(
            log.get('blockNumber'), 0,
        )
        return token_amount, token_usd_amount

    if event_name == 'Swap':
        amount0In, amount0In_usd = token_native_and_usd_amount(
            token='token0',
            token_type='amount0In',
            token_price_map=token0_price_map,
        )
        amount0Out, amount0Out_usd = token_native_and_usd_amount(
            token='token0',
            token_type='amount0Out',
            token_price_map=token0_price_map,
        )
        amount1In, amount1In_usd = token_native_and_usd_amount(
            token='token1',
            token_type='amount1In',
            token_price_map=token1_price_map,
        )
        amount1Out, amount1Out_usd = token_native_and_usd_amount(
            token='token1',
            token_type='amount1Out',
            token_price_map=token1_price_map,
        )

        token0_amount = abs(amount0Out - amount0In)
        token1_amount = abs(amount1Out - amount1In)

        token0_amount_usd = abs(amount0Out_usd - amount0In_usd)
        token1_amount_usd = abs(amount1Out_usd - amount1In_usd)

    elif event_name == 'Mint' or event_name == 'Burn':
        token0_amount, token0_amount_usd = token_native_and_usd_amount(
            token='token0',
            token_type='amount0',
            token_price_map=token0_price_map,
        )
        token1_amount, token1_amount_usd = token_native_and_usd_amount(
            token='token1',
            token_type='amount1',
            token_price_map=token1_price_map,
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
            trade_volume_usd = (
                token1_amount_usd
                if token1_amount_usd > token0_amount_usd
                else token0_amount_usd
            )
        else:
            trade_volume_usd = (
                token1_amount_usd if token1_amount_usd else token0_amount_usd
            )

        # calculate uniswap LP fee
        trade_fee_usd = (
            token1_amount_usd * 0.003
            if token1_amount_usd
            else token0_amount_usd * 0.003
        )  # uniswap LP fee rate

        # set final usd amount for swap
        log['trade_amount_usd'] = trade_volume_usd

        return (
            trade_data(
                totalTradesUSD=trade_volume_usd,
                totalFeeUSD=trade_fee_usd,
                token0TradeVolume=token0_amount,
                token1TradeVolume=token1_amount,
                token0TradeVolumeUSD=token0_amount_usd,
                token1TradeVolumeUSD=token1_amount_usd,
            ),
            log,
        )

    trade_volume_usd = token0_amount_usd + token1_amount_usd

    # set final usd amount for other events
    log['trade_amount_usd'] = trade_volume_usd

    return (
        trade_data(
            totalTradesUSD=trade_volume_usd,
            totalFeeUSD=0.0,
            token0TradeVolume=token0_amount,
            token1TradeVolume=token1_amount,
            token0TradeVolumeUSD=token0_amount_usd,
            token1TradeVolumeUSD=token1_amount_usd,
        ),
        log,
    )


# asynchronously get trades on a pair contract
async def get_pair_trade_volume(
    data_source_contract_address,
    min_chain_height,
    max_chain_height,
    redis_conn: aioredis.Redis,
    rpc_helper: RpcHelper,
    fetch_timestamp=True,
):

    data_source_contract_address = Web3.toChecksumAddress(
        data_source_contract_address,
    )
    block_details_dict = dict()

    if fetch_timestamp:
        try:
            block_details_dict = await get_block_details_in_block_range(
                from_block=min_chain_height,
                to_block=max_chain_height,
                redis_conn=redis_conn,
                rpc_helper=rpc_helper,
            )
        except Exception as err:
            core_logger.opt(exception=True).error(
                (
                    'Error attempting to get block details of to_block {}:'
                    ' {}, retrying again'
                ),
                max_chain_height,
                err,
            )
            raise err

    pair_per_token_metadata = await get_pair_metadata(
        pair_address=data_source_contract_address,
        redis_conn=redis_conn,
        rpc_helper=rpc_helper,
    )
    token0_price_map, token1_price_map = await asyncio.gather(
        get_token_price_in_block_range(
            token_metadata=pair_per_token_metadata['token0'],
            from_block=min_chain_height,
            to_block=max_chain_height,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
            debug_log=False,
        ),
        get_token_price_in_block_range(
            token_metadata=pair_per_token_metadata['token1'],
            from_block=min_chain_height,
            to_block=max_chain_height,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
            debug_log=False,
        ),
    )

    # fetch logs for swap, mint & burn
    event_sig, event_abi = get_event_sig_and_abi(
        UNISWAP_TRADE_EVENT_SIGS,
        UNISWAP_EVENTS_ABI,
    )

    events_log = await rpc_helper.get_events_logs(
        **{
            'contract_address': data_source_contract_address,
            'to_block': max_chain_height,
            'from_block': min_chain_height,
            'topics': [event_sig],
            'event_abi': event_abi,
            'redis_conn': redis_conn,
        },
    )

    # group logs by txHashs ==> {txHash: [logs], ...}
    grouped_by_tx = dict()
    [
        grouped_by_tx[log.transactionHash.hex()].append(log)
        if log.transactionHash.hex() in grouped_by_tx
        else grouped_by_tx.update({log.transactionHash.hex(): [log]})
        for log in events_log
    ]

    # init data models with empty/0 values
    epoch_results = epoch_event_trade_data(
        Swap=event_trade_data(
            logs=[],
            trades=trade_data(
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
            logs=[],
            trades=trade_data(
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
            logs=[],
            trades=trade_data(
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
        # shift Burn logs in end of list to check if equal size of mint already exist
        # and then cancel out burn with mint
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
                tx_hash_trades += (
                    trades_result  # swap in single txHash should be added
                )

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


async def get_total_value_locked(
    data_source_contract_address,
    min_chain_height,
    max_chain_height,
    redis_conn: aioredis.Redis,
    rpc_helper: RpcHelper,
    fetch_timestamp=True,
):
    data_source_contract_address = Web3.toChecksumAddress(data_source_contract_address)
    override_address = Web3.toChecksumAddress('0x' + '1' * 40)
    block_details_dict = dict()
    if fetch_timestamp:
        try:
            block_details_dict = await get_block_details_in_block_range(
                from_block=min_chain_height,
                to_block=max_chain_height,
                redis_conn=redis_conn,
                rpc_helper=rpc_helper,
            )
        except Exception as err:
            core_logger.opt(exception=True).error(
                (
                    'Error attempting to get block details of to_block {}:'
                    ' {}, retrying again'
                ),
                max_chain_height,
                err,
            )
            raise err
        pair_per_token_metadata = await get_pair_metadata(
            pair_address=pair_address,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
        )

    core_logger.debug(
        (
            'total pair reserves fetched block details for epoch for:'
            f' {pair_address}'
        ),
    )

    token0_price_map, token1_price_map = await asyncio.gather(
        get_token_price_in_block_range(
            token_metadata=pair_per_token_metadata['token0'],
            from_block=min_chain_height,
            to_block=max_chain_height,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
            debug_log=False,
        ),
        get_token_price_in_block_range(
            token_metadata=pair_per_token_metadata['token1'],
            from_block=min_chain_height,
            to_block=max_chain_height,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
            debug_log=False,
        ),
    )

    # TODO do not rpc call every snapshot, instead rpc call on genesis then process epoch for mint/burn and increment
    pair_abi_dict = get_contract_abi_dict(pair_contract_abi)
    overrides = {
        override_address: '0x608060405234801561001057600080fd5b506004361061002b5760003560e01c8063802036f514610030575b600080fd5b61004a600480360381019061004591906106da565b610060565b6040516100579190610859565b60405180910390f35b606060008273ffffffffffffffffffffffffffffffffffffffff1663d0c93a7c6040518163ffffffff1660e01b8152600401602060405180830381865afa1580156100af573d6000803e3d6000fd5b505050506040513d601f19601f820116820180604052508101906100d391906108b4565b905060008373ffffffffffffffffffffffffffffffffffffffff16633850c7bd6040518163ffffffff1660e01b81526004016040805180830381865afa158015610121573d6000803e3d6000fd5b505050506040513d601f19601f82011682018060405250810190610145919061090d565b91505060007ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff27618905060007ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff276186101999061097c565b9050600084600184846101ac91906109c4565b6101b69190610a1f565b6101c09190610aa9565b60020b67ffffffffffffffff8111156101dc576101db610b13565b5b60405190808252806020026020018201604052801561020a5781602001602082028036833780820191505090505b5090506000806008878661021e9190610aa9565b60020b901d90506000600888866102359190610aa9565b60020b901d90505b8060010b8260010b1361037a5760008a73ffffffffffffffffffffffffffffffffffffffff16635339c296846040518263ffffffff1660e01b81526004016102859190610b5e565b602060405180830381865afa1580156102a2573d6000803e3d6000fd5b505050506040513d601f19601f820116820180604052508101906102c69190610baf565b90505b600081146103665760006102dc826104f6565b90508060ff166001901b8218915060008a8260ff1660088760010b60020b901b176103079190610bdc565b90508860020b8160020b1215801561032557508760020b8160020b13155b1561035f578087878061033790610c19565b98508151811061034a57610349610c61565b5b602002602001019060020b908160020b815250505b50506102c9565b50818061037290610c90565b92505061023d565b8267ffffffffffffffff81111561039457610393610b13565b5b6040519080825280602002602001820160405280156103c757816020015b60608152602001906001900390816103b25790505b50985060005b838110156104e8576000808c73ffffffffffffffffffffffffffffffffffffffff1663f30dba9388858151811061040757610406610c61565b5b60200260200101516040518263ffffffff1660e01b815260040161042b9190610cc9565b61010060405180830381865afa158015610449573d6000803e3d6000fd5b505050506040513d601f19601f8201168201806040525081019061046d9190610e12565b50505050505091509150818188858151811061048c5761048b610c61565b5b60200260200101516040516020016104a693929190610f5d565b6040516020818303038152906040528c84815181106104c8576104c7610c61565b5b6020026020010181905250505080806104e090610c19565b9150506103cd565b505050505050505050919050565b600080821161050457600080fd5b60ff905060006fffffffffffffffffffffffffffffffff801683161115610539576080816105329190610fa7565b9050610541565b608082901c91505b600067ffffffffffffffff80168316111561056a576040816105639190610fa7565b9050610572565b604082901c91505b600063ffffffff801683161115610597576020816105909190610fa7565b905061059f565b602082901c91505b600061ffff8016831611156105c2576010816105bb9190610fa7565b90506105ca565b601082901c91505b600060ff8016831611156105ec576008816105e59190610fa7565b90506105f4565b600882901c91505b6000600f831611156106145760048161060d9190610fa7565b905061061c565b600482901c91505b600060038316111561063c576002816106359190610fa7565b9050610644565b600282901c91505b60006001831611156106605760018161065d9190610fa7565b90505b919050565b600080fd5b600073ffffffffffffffffffffffffffffffffffffffff82169050919050565b60006106958261066a565b9050919050565b60006106a78261068a565b9050919050565b6106b78161069c565b81146106c257600080fd5b50565b6000813590506106d4816106ae565b92915050565b6000602082840312156106f0576106ef610665565b5b60006106fe848285016106c5565b91505092915050565b600081519050919050565b600082825260208201905092915050565b6000819050602082019050919050565b600081519050919050565b600082825260208201905092915050565b60005b8381101561076d578082015181840152602081019050610752565b60008484015250505050565b6000601f19601f8301169050919050565b600061079582610733565b61079f818561073e565b93506107af81856020860161074f565b6107b881610779565b840191505092915050565b60006107cf838361078a565b905092915050565b6000602082019050919050565b60006107ef82610707565b6107f98185610712565b93508360208202850161080b85610723565b8060005b85811015610847578484038952815161082885826107c3565b9450610833836107d7565b925060208a0199505060018101905061080f565b50829750879550505050505092915050565b6000602082019050818103600083015261087381846107e4565b905092915050565b60008160020b9050919050565b6108918161087b565b811461089c57600080fd5b50565b6000815190506108ae81610888565b92915050565b6000602082840312156108ca576108c9610665565b5b60006108d88482850161089f565b91505092915050565b6108ea8161066a565b81146108f557600080fd5b50565b600081519050610907816108e1565b92915050565b6000806040838503121561092457610923610665565b5b6000610932858286016108f8565b92505060206109438582860161089f565b9150509250929050565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052601160045260246000fd5b60006109878261087b565b91507fffffffffffffffffffffffffffffffffffffffffffffffffffffffffff80000082036109b9576109b861094d565b5b816000039050919050565b60006109cf8261087b565b91506109da8361087b565b92508282039050627fffff81137fffffffffffffffffffffffffffffffffffffffffffffffffffffffffff80000082121715610a1957610a1861094d565b5b92915050565b6000610a2a8261087b565b9150610a358361087b565b925082820190507fffffffffffffffffffffffffffffffffffffffffffffffffffffffffff8000008112627fffff82131715610a7457610a7361094d565b5b92915050565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052601260045260246000fd5b6000610ab48261087b565b9150610abf8361087b565b925082610acf57610ace610a7a565b5b600160000383147fffffffffffffffffffffffffffffffffffffffffffffffffffffffffff80000083141615610b0857610b0761094d565b5b828205905092915050565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052604160045260246000fd5b60008160010b9050919050565b610b5881610b42565b82525050565b6000602082019050610b736000830184610b4f565b92915050565b6000819050919050565b610b8c81610b79565b8114610b9757600080fd5b50565b600081519050610ba981610b83565b92915050565b600060208284031215610bc557610bc4610665565b5b6000610bd384828501610b9a565b91505092915050565b6000610be78261087b565b9150610bf28361087b565b9250828202610c008161087b565b9150808214610c1257610c1161094d565b5b5092915050565b6000610c2482610b79565b91507fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff8203610c5657610c5561094d565b5b600182019050919050565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052603260045260246000fd5b6000610c9b82610b42565b9150617fff8203610caf57610cae61094d565b5b600182019050919050565b610cc38161087b565b82525050565b6000602082019050610cde6000830184610cba565b92915050565b60006fffffffffffffffffffffffffffffffff82169050919050565b610d0981610ce4565b8114610d1457600080fd5b50565b600081519050610d2681610d00565b92915050565b600081600f0b9050919050565b610d4281610d2c565b8114610d4d57600080fd5b50565b600081519050610d5f81610d39565b92915050565b60008160060b9050919050565b610d7b81610d65565b8114610d8657600080fd5b50565b600081519050610d9881610d72565b92915050565b600063ffffffff82169050919050565b610db781610d9e565b8114610dc257600080fd5b50565b600081519050610dd481610dae565b92915050565b60008115159050919050565b610def81610dda565b8114610dfa57600080fd5b50565b600081519050610e0c81610de6565b92915050565b600080600080600080600080610100898b031215610e3357610e32610665565b5b6000610e418b828c01610d17565b9850506020610e528b828c01610d50565b9750506040610e638b828c01610b9a565b9650506060610e748b828c01610b9a565b9550506080610e858b828c01610d89565b94505060a0610e968b828c016108f8565b93505060c0610ea78b828c01610dc5565b92505060e0610eb88b828c01610dfd565b9150509295985092959890939650565b60008160801b9050919050565b6000610ee082610ec8565b9050919050565b610ef8610ef382610ce4565b610ed5565b82525050565b6000610f0982610ec8565b9050919050565b610f21610f1c82610d2c565b610efe565b82525050565b60008160e81b9050919050565b6000610f3f82610f27565b9050919050565b610f57610f528261087b565b610f34565b82525050565b6000610f698286610ee7565b601082019150610f798285610f10565b601082019150610f898284610f46565b600382019150819050949350505050565b600060ff82169050919050565b6000610fb282610f9a565b9150610fbd83610f9a565b9250828203905060ff811115610fd657610fd561094d565b5b9291505056fea2646970667358221220221231006ad914be8e1c336c2daae4906e7356f2050aed1a9d0b63a212ece14164736f6c63430008130033',
    }
    params = [data_source_contract_address]
    # get tick data for
    response = await rpc_helper.batch_eth_call_on_block_range(
        abi_dict=pair_abi_dict,
        function_name='getTicks',
        contract_address=override_address,
        from_block=min_chain_height,
        to_block=min_chain_height,
        redis_conn=redis_conn,
        params=params,
        overrides=overrides,
    )

    ticks_list = transform_tick_bytes_to_tvl(response)

    # TODO  process tick data and calc tvl
    tvl = 0

    # process mint/burn events in epoch
    event_sig, event_abi = get_event_sig_and_abi(
        {
            'Mint': UNISWAP_TRADE_EVENT_SIGS['Mint'],
            'Burn': UNISWAP_TRADE_EVENT_SIGS['Burn'],
        },
        {
            'Mint': UNISWAP_EVENTS_ABI['Mint'],
            'Burn': UNISWAP_EVENTS_ABI['Burn'],
        },
    )

    events_log = await rpc_helper.get_events_logs(
        **{
            'contract_address': data_source_contract_address,
            'to_block': max_chain_height,
            'from_block': min_chain_height,
            'topics': [event_sig],
            'event_abi': event_abi,
            'redis_conn': redis_conn,
        },
    )

    # group logs by mint/burn
    grouped_by_event = dict()
    grouped_by_event['Burn'] = []
    grouped_by_event['Mint'] = []

    [
        grouped_by_event['Mint'].append(log)
        if log.topics[0] == UNISWAP_EVENTS_ABI['Mint']
        else grouped_by_event['Burn'].append(log)
        for log in events_log
    ]

    #
