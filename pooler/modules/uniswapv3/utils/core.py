import asyncio
from functools import reduce
import json

from redis import asyncio as aioredis
from web3 import Web3

from .constants import UNISWAP_EVENTS_ABI, UNISWAPV3_FEE_DIV
from .constants import UNISWAP_TRADE_EVENT_SIGS
from .helpers import get_pair_metadata
from .models.data_models import epoch_event_trade_data
from .models.data_models import event_trade_data
from .models.data_models import trade_data
from .pricing import (
    get_token_price_in_block_range,
)
from pooler.modules.uniswapv3.total_value_locked import calculate_reserves, get_tick_info, get_token0_in_pool, get_token1_in_pool
from pooler.modules.uniswapv3.total_value_locked import get_events
from pooler.utils.default_logger import logger
from pooler.utils.rpc import get_event_sig_and_abi
from pooler.utils.rpc import RpcHelper
from pooler.utils.snapshot_utils import (
    get_block_details_in_block_range,
)

core_logger = logger.bind(module="PowerLoom|UniswapCore")


async def get_pair_reserves(
    pair_address,
    from_block,
    to_block,
    redis_conn: aioredis.Redis,
    rpc_helper: RpcHelper,
    fetch_timestamp=False,
):
    core_logger.debug(
        f"Starting pair total reserves query for: {pair_address}",
    )
    pair_address = Web3.to_checksum_address(pair_address)

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
                    "Error attempting to get block details of block-range"
                    " {}-{}: {}, retrying again"
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
        ("total pair reserves fetched block details for epoch for:" f" {pair_address}"),
    )

    token0_price_map, token1_price_map = await asyncio.gather(
        get_token_price_in_block_range(
            token_metadata=pair_per_token_metadata["token0"],
            from_block=from_block,
            to_block=to_block,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
            debug_log=False,
    
        ),
        get_token_price_in_block_range(
            token_metadata=pair_per_token_metadata["token1"],
            from_block=from_block,
            to_block=to_block,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
            debug_log=False,
            
        ),
    )

    core_logger.debug(
        f"Total reserves fetched token prices for: {pair_address}",
    )

    core_logger.debug(f"token0_price_map: {token0_price_map}") 
    core_logger.debug(f"token1_price_map: {token1_price_map}")  

    initial_reserves = await calculate_reserves(
        pair_address,
        from_block,
        pair_per_token_metadata,
        rpc_helper,
        redis_conn
    )

    core_logger.debug(f"initial_reserves: {initial_reserves}")

    core_logger.debug(
        f"Total reserves fetched tick data for {pair_address} of {initial_reserves} for block {from_block}",
    )

    # grab mint/burn events in range
    
    events = await get_events(
        pair_address=pair_address,
        rpc=rpc_helper,
        from_block=from_block,
        to_block=to_block,
        redis_con=redis_conn,
    )

    core_logger.debug(
        f"Total reserves fetched event data for : {pair_address}",
    )
    # sum burn and mint each block

    token0Amount = initial_reserves[0]
    token1Amount = initial_reserves[1]

    pair_reserves_dict = dict() 
    
    block_event_dict = dict()

    for block_num in range(from_block, to_block + 1):
        block_event_dict[block_num] = filter(lambda x: x if x.get("blockNumber") == block_num else None, events)


    for block_num, events in block_event_dict.items():
        events_in_block = block_event_dict.get(block_num, []) 

        token0Amount += reduce(
            lambda acc, event: acc + event['args']['amount0']
            if event['name'] == 'Mint' 
            else acc - event['args']['amount0'], events_in_block, 0)
        token1Amount += reduce(
            lambda acc, event: acc + event['args']['amount0']
            if event['name'] == 'Mint' 
            else acc - event['args']['amount1'], events_in_block, 0)
        
        token0USD = token0Amount * token0_price_map.get(block_num, 0) * (10 ** -int(pair_per_token_metadata["token0"]["decimals"]))
        token1USD = token1Amount * (token1_price_map.get(block_num, 0)) * (10 ** -int(pair_per_token_metadata["token1"]["decimals"]))
        

        token0Price = token0_price_map.get(block_num, 0)
        token1Price = token1_price_map.get(block_num, 0)

        current_block_details = block_details_dict.get(block_num, None)

        timestamp = (   
            current_block_details.get(
                "timestamp",
                None,
            )
            if current_block_details
            else None
        )

        pair_reserves_dict[block_num] = {
            "token0": {"reserves": token0Amount, "decimals": pair_per_token_metadata["token0"]["decimals"]},
            "token1": {"reserves": token1Amount, "decimals": pair_per_token_metadata["token1"]["decimals"]},
            "token0USD": token0USD,
            "token1USD": token1USD,
            "token0Price": token0Price,
            "token1Price": token1Price,
            "timestamp": timestamp,
        }
    
    
    core_logger.debug(
        (
            "Calculated pair total reserves for epoch-range:"
            f" {from_block} - {to_block} | pair_contract: {pair_address}"
        ),
    )

    return pair_reserves_dict
        
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
        if log['args'].get(token_type) == 0:
            return 0, 0

        token_amount = log['args'].get(token_type) / 10 ** int(
            pair_per_token_metadata[token]["decimals"],
        )
        token_usd_amount = token_amount * token_price_map.get(
            log.get("blockNumber"),
            0,
        )
        return token_amount, token_usd_amount

    if event_name == "Swap":
        amount0, amount0_usd = token_native_and_usd_amount(
            token="token0",
            token_type="amount0",
            token_price_map=token0_price_map,
        )
        amount1, amount1_usd = token_native_and_usd_amount(
            token="token1",
            token_type="amount1",
            token_price_map=token1_price_map,
        )

        
        token0_amount = abs(amount0)
        token1_amount = abs(amount1)

        token0_amount_usd = abs(amount0_usd)
        token1_amount_usd = abs(amount1_usd)

    elif event_name == "Mint" or event_name == "Burn":
        token0_amount, token0_amount_usd = token_native_and_usd_amount(
            token="token0",
            token_type="amount0",
            token_price_map=token0_price_map,
        )
        token1_amount, token1_amount_usd = token_native_and_usd_amount(
            token="token1",
            token_type="amount1",
            token_price_map=token1_price_map,
        )

    trade_volume_usd = 0
    trade_fee_usd = 0
    fee = int(pair_per_token_metadata['pair']['fee']) / UNISWAPV3_FEE_DIV

    block_details = block_details_dict.get(int(log.get("blockNumber", 0)), {})
    log = json.loads(Web3.to_json(log))
    log["token0_amount"] = token0_amount
    log["token1_amount"] = token1_amount
    log["timestamp"] = block_details.get("timestamp", "")
    # pop unused log props
    log.pop("blockHash", None)
    log.pop("transactionIndex", None)

    # if event is 'Swap' then only add single token in total volume calculation
    if event_name == "Swap":
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
            token1_amount_usd * fee
            if token1_amount_usd
            else token0_amount_usd * fee
        )  # uniswap LP fee rate

        # set final usd amount for swap
        log["trade_amount_usd"] = trade_volume_usd

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
    log["trade_amount_usd"] = trade_volume_usd

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


# asynchronously get trades on a pair contract
async def get_pair_trade_volume(
    data_source_contract_address,
    min_chain_height,
    max_chain_height,
    redis_conn: aioredis.Redis,
    rpc_helper: RpcHelper,
    fetch_timestamp=True,
):
    data_source_contract_address = Web3.to_checksum_address(
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
                    "Error attempting to get block details of to_block {}:"
                    " {}, retrying again"
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
            token_metadata=pair_per_token_metadata["token0"],
            from_block=min_chain_height,
            to_block=max_chain_height,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
            debug_log=False,
        ),
        get_token_price_in_block_range(
            token_metadata=pair_per_token_metadata["token1"],
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
            "contract_address": data_source_contract_address,
            "to_block": max_chain_height,
            "from_block": min_chain_height,
            "topics": [event_sig],
            "event_abi": event_abi,
            "redis_conn": redis_conn,
        },
    )
    
    # group logs by txHashs ==> {txHash: [logs], ...}
    grouped_by_tx = dict()
    [
        grouped_by_tx[log['transactionHash'].hex()].append(log)
        if log['transactionHash'].hex() in grouped_by_tx
        else grouped_by_tx.update({log['transactionHash'].hex(): [log]})
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
        logs = sorted(logs, key=lambda x: x['event'], reverse=True)

        # iterate over each txHash logs
        for log in logs:
            # fetch trade value fog log
            trades_result, processed_log = extract_trade_volume_log(
                event_name=log['event'],
                log=log,
                pair_per_token_metadata=pair_per_token_metadata,
                token0_price_map=token0_price_map,
                token1_price_map=token1_price_map,
                block_details_dict=block_details_dict,
            )
        
            if log['event'] == "Swap":
                epoch_results.Swap.logs.append(processed_log)
                epoch_results.Swap.trades += trades_result
                tx_hash_trades += trades_result  # swap in single txHash should be added

            elif log['event'] == "Mint":
                epoch_results.Mint.logs.append(processed_log)
                epoch_results.Mint.trades += trades_result

            elif log['event'] == "Burn":
                epoch_results.Burn.logs.append(processed_log)
                epoch_results.Burn.trades += trades_result

        # At the end of txHash logs we must normalize trade values, so it don't affect result of other txHash logs
        epoch_results.Trades += abs(tx_hash_trades)
    epoch_trade_logs = epoch_results.dict()
    max_block_details = block_details_dict.get(max_chain_height, dict())
    max_block_timestamp = max_block_details.get("timestamp", None)
    epoch_trade_logs.update({"timestamp": max_block_timestamp})
    core_logger.debug(f"epoch_trade_logs: {epoch_trade_logs}")
    return epoch_trade_logs


async def get_liquidity_depth(
    pair_address,
    from_block,
    to_block,
    redis_conn: aioredis.Redis,
    rpc_helper: RpcHelper,
    fetch_timestamp=False,
):
    liquidity_depth_dict = dict()
    core_logger.debug(
    f"Starting liquidity depth query for: {pair_address}",
    )
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
                    "Error attempting to get block details of block-range"
                    " {}-{}: {}, retrying again"
                ),
                from_block,
                to_block,
                err,
            )
            raise err
    else:
        block_details_dict = dict()

    pair_address = Web3.to_checksum_address(pair_address)

    pair_per_token_metadata = await get_pair_metadata(
        pair_address=pair_address,
        redis_conn=redis_conn,
        rpc_helper=rpc_helper,
    )

    token0_price_map, token1_price_map = await asyncio.gather(
        get_token_price_in_block_range(
            token_metadata=pair_per_token_metadata["token0"],
            from_block=from_block,
            to_block=to_block,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
            debug_log=False,
    
        ),
        get_token_price_in_block_range(
            token_metadata=pair_per_token_metadata["token1"],
            from_block=from_block,
            to_block=to_block,
            redis_conn=redis_conn,
            rpc_helper=rpc_helper,
            debug_log=False,
            
        ),
    )

    core_logger.debug('grabbed pair per token metadata for liquidity depth')
    # grab ticks in range and calculate initial liquidity depth

    ticks_list, slot0 = await get_tick_info(
        rpc_helper=rpc_helper,
        pair_address=pair_address,
        from_block=from_block,
        redis_conn=redis_conn,
    )
    core_logger.debug('the dog jumped over the tracks')
    liquidity_depth_initial = calculate_liquidity_depth(
        ticks_list, 
        slot0[0],
        pair_per_token_metadata)
    
    core_logger.debug(
        "initial liquidity depth fetched block details for epoch for:" f" {pair_address} moose ")
    

    for block_num in range(from_block, to_block + 1):
        liquidity_depth_dict[block_num] = liquidity_depth_initial
        liquidity_depth_dict[block_num]['prices'] = {
            "token0": token0_price_map.get(block_num, 0),
            "token1": token1_price_map.get(block_num, 0),
        }
    
    events = await get_events(
        pair_address=pair_address,
        rpc=rpc_helper,
        from_block=from_block,
        to_block=to_block,
        redis_con=redis_conn,
    )

    core_logger.debug(
        f"Events fetched for liquidity depth: {events}") 
    events_by_block = dict()
    for event in events:
        events_by_block[event["blockNumber"]] = events_by_block.get(
            event["blockNumber"], []
        )
        events_by_block[event["blockNumber"]].append(event)


    for block_num in range(from_block + 1, to_block + 1):
        
        events = events_by_block.get(block_num, [])
        for event in events:
            amount0 = event["args"]['amount0']
            amount1 = event["args"]['amount1']
            if event["name"] == "Mint":
                liquidity_depth_dict[block_num]["token0"]["amount"] += amount0
                liquidity_depth_dict[block_num]["token1"]["amount"] += amount1
            else:
                liquidity_depth_dict[block_num]["token0"]["amount"] -= amount0
                liquidity_depth_dict[block_num]["token1"]["amount"] -= amount1

        current_block_details = block_details_dict.get(block_num, None)

        timestamp = (   
            current_block_details.get(
                "timestamp",
                None,
            )
            if current_block_details
            else None
        )
        liquidity_depth_dict[block_num]['timestamp'] = timestamp

    return liquidity_depth_dict





def calculate_liquidity_depth(
        ticks,
        sqrt_price,
        pair_metadata,
    ):  
    liquidity_depth_dict = dict()
    sqrt_price = sqrt_price / 2 ** 96
    liquidity_total = 0
    token0_liquidity = 0
    token1_liquidity = 0
    tick_spacing = 10

    if len(ticks) == 0:
        return (0, 0)

    if pair_metadata["pair"]["fee"] == 3000:
        tick_spacing = 60
    elif pair_metadata["pair"]["fee"] == 10000:
        tick_spacing = 200
# https://atiselsts.github.io/pdfs/uniswap-v3-liquidity-math.pdf
    for i in range(len(ticks)):
        tick = ticks[i]
        liquidity_net = tick["liquidity_net"]
        idx = tick["idx"]
        next_idx = idx + ticks[i + 1]["idx"] if i < len(ticks) - 1 else idx + tick_spacing
        liquidity_total += liquidity_net
        sqrtPriceLow = 1.0001 ** (idx // 2) 
        sqrtPriceHigh = 1.0001 ** ((next_idx) // 2)
        if sqrt_price <= sqrtPriceLow:
            token0_liquidity += get_token0_in_pool(
                liquidity_total,
                sqrtPriceLow,
                sqrtPriceHigh,
            )
            liquidity_depth_dict[idx] = {
                "token0": {
                    "address": pair_metadata["token0"]['address'],
                    "amount": abs(token0_liquidity),
                    "decimals": pair_metadata["token0"]["decimals"],
                },
                "token1": {
                    "address": pair_metadata["token1"]['address'],
                    "amount": 0,
                    "decimals": pair_metadata["token1"]["decimals"],
                },

            }
        elif sqrt_price >= sqrtPriceHigh:
            token1_liquidity += get_token1_in_pool(
                liquidity_total,
                sqrtPriceLow,
                sqrtPriceHigh,
            )
            liquidity_depth_dict[idx] = {
                "token0": {
                    "token": pair_metadata["token1"]['address'],
                    "amount": abs(token1_liquidity),
                    "decimals": pair_metadata["token1"]["decimals"],
                },
                "token1": {
                    "token": pair_metadata["token0"]['address'],
                    "amount": 0,
                    "decimals": pair_metadata["token0"]["decimals"],
                }

            }
        else: 
            token0_liquidity += get_token0_in_pool(
                liquidity_total,
                sqrt_price,
                sqrtPriceHigh,
            )
            
            token1_liquidity += get_token1_in_pool(
                liquidity_total,
                sqrtPriceLow,
                sqrt_price,
            )   

            liquidity_depth_dict[idx] = {
                "token0": {
                    "token": pair_metadata["token0"]['address'],
                    "amount": abs(token0_liquidity),
                    "decimals": pair_metadata["token0"]["decimals"],
                },
                "token1": {
                    "token": pair_metadata["token1"]['address'],
                    "amount": abs(token1_liquidity),
                    "decimals": pair_metadata["token1"]["decimals"],
                }

            }


    return liquidity_depth_dict

    
