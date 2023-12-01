import asyncio
import functools
from functools import reduce
import json

from redis import asyncio as aioredis
from web3 import Web3

from ..redis_keys import uniswap_pair_contract_tokens_addresses
from ..redis_keys import uniswap_cached_block_height_token_eth_price
from ..redis_keys import uniswap_pair_contract_tokens_data
from ..redis_keys import uniswap_tokens_pair_map
from ..settings.config import settings as worker_settings
from .constants import current_node
from .constants import erc20_abi
from .constants import pair_contract_abi
from .constants import quoter_1inch_contract_abi
from pooler.utils.default_logger import logger
from pooler.utils.rpc import RpcHelper, get_contract_abi_dict


helper_logger = logger.bind(module="PowerLoom|Uniswap|Helpers")


def get_maker_pair_data(prop):
    prop = prop.lower()
    if prop.lower() == "name":
        return "Maker"
    elif prop.lower() == "symbol":
        return "MKR"
    else:
        return "Maker"


async def get_pair(
    factory_contract_obj,
    token0,
    token1,
    fee,
    redis_conn: aioredis.Redis,
    rpc_helper: RpcHelper,
):
    # check if pair cache exists
    pair_address_cache = await redis_conn.hget(
        uniswap_tokens_pair_map,
        f"{Web3.to_checksum_address(token0)}-{Web3.to_checksum_address(token1)}|{fee}",
    )
    if pair_address_cache:
        pair_address_cache = pair_address_cache.decode("utf-8")
        return Web3.to_checksum_address(pair_address_cache)

    tasks = [
        factory_contract_obj.functions.getPool(
            Web3.to_checksum_address(token0),
            Web3.to_checksum_address(token1),
            fee,
        ),
    ]

    result = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)
    pair = result[0]
    # cache the pair address
    await redis_conn.hset(
        name=uniswap_tokens_pair_map,
        mapping={
            f"{Web3.to_checksum_address(token0)}-{Web3.to_checksum_address(token1)}|{fee}": Web3.to_checksum_address(
                pair,
            ),
        },
    )

    return pair


async def get_pair_metadata(
    pair_address,
    redis_conn: aioredis.Redis,
    rpc_helper: RpcHelper,
):
    """
    returns information on the tokens contained within a pair contract - name, symbol, decimals of token0 and token1
    also returns pair symbol by concatenating {token0Symbol}-{token1Symbol}
    """
    try:
        pair_address = Web3.to_checksum_address(pair_address)

        # check if cache exist
        (
            pair_token_addresses_cache,
            pair_tokens_data_cache,
        ) = await asyncio.gather(
            redis_conn.hgetall(
                uniswap_pair_contract_tokens_addresses.format(pair_address),
            ),
            redis_conn.hgetall(
                uniswap_pair_contract_tokens_data.format(pair_address),
            ),
        )

        # parse addresses cache or call eth rpc
        token0Addr = None
        token1Addr = None
        if pair_token_addresses_cache:
            token0Addr = Web3.to_checksum_address(
                pair_token_addresses_cache[b"token0Addr"].decode("utf-8"),
            )
            token1Addr = Web3.to_checksum_address(
                pair_token_addresses_cache[b"token1Addr"].decode("utf-8"),
            )
            fee = pair_token_addresses_cache[b"fee"].decode("utf-8")
        else:
            pair_contract_obj = current_node["web3_client"].eth.contract(
                address=Web3.to_checksum_address(pair_address),
                abi=pair_contract_abi,
            )
            token0Addr, token1Addr, fee = await rpc_helper.web3_call(
                [
                    pair_contract_obj.functions.token0(),
                    pair_contract_obj.functions.token1(),
                    pair_contract_obj.functions.fee(),
                ],
                redis_conn=redis_conn,
            )

            await redis_conn.hset(
                name=uniswap_pair_contract_tokens_addresses.format(
                    pair_address,
                ),
                mapping={
                    "token0Addr": token0Addr,
                    "token1Addr": token1Addr,
                    "fee": fee,
                },
            )

        # token0 contract
        token0 = current_node["web3_client"].eth.contract(
            address=Web3.to_checksum_address(token0Addr),
            abi=erc20_abi,
        )
        # token1 contract
        token1 = current_node["web3_client"].eth.contract(
            address=Web3.to_checksum_address(token1Addr),
            abi=erc20_abi,
        )

        # parse token data cache or call eth rpc
        if pair_tokens_data_cache:
            token0_decimals = pair_tokens_data_cache[b"token0_decimals"].decode(
                "utf-8",
            )
            token1_decimals = pair_tokens_data_cache[b"token1_decimals"].decode(
                "utf-8",
            )
            token0_symbol = pair_tokens_data_cache[b"token0_symbol"].decode(
                "utf-8",
            )
            token1_symbol = pair_tokens_data_cache[b"token1_symbol"].decode(
                "utf-8",
            )
            token0_name = pair_tokens_data_cache[b"token0_name"].decode("utf-8")
            token1_name = pair_tokens_data_cache[b"token1_name"].decode("utf-8")
        else:
            tasks = list()

            # special case to handle maker token
            maker_token0 = None
            maker_token1 = None
            # if Web3.to_checksum_address(
            #     worker_settings.contract_addresses.MAKER,
            # ) == Web3.to_checksum_address(token0Addr):
            #     token0_name = get_maker_pair_data('name')
            #     token0_symbol = get_maker_pair_data('symbol')
            #     maker_token0 = True
            # else:
            tasks.append(token0.functions.name())
            tasks.append(token0.functions.symbol())
            tasks.append(token0.functions.decimals())


            # if Web3.to_checksum_address(
            #     worker_settings.contract_addresses.MAKER,
            # ) == Web3.to_checksum_address(token1Addr):
            #     token1_name = get_maker_pair_data('name')
            #     token1_symbol = get_maker_pair_data('symbol')
            #     maker_token1 = True
            # else:
            tasks.append(token1.functions.name())
            tasks.append(token1.functions.symbol())
            tasks.append(token1.functions.decimals())

            if maker_token1:
                [
                    token0_name,
                    token0_symbol,
                    token0_decimals,
                    token1_decimals,
                ] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)
            elif maker_token0:
                [
                    token0_decimals,
                    token1_name,
                    token1_symbol,
                    token1_decimals,
                ] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)
            else:
                [
                    token0_name,
                    token0_symbol,
                    token0_decimals,
                    token1_name,
                    token1_symbol,
                    token1_decimals,
                ] = await rpc_helper.web3_call(tasks, redis_conn=redis_conn)

            await redis_conn.hset(
                name=uniswap_pair_contract_tokens_data.format(pair_address),
                mapping={
                    "token0_name": token0_name,
                    "token0_symbol": token0_symbol,
                    "token0_decimals": token0_decimals,
                    "token1_name": token1_name,
                    "token1_symbol": token1_symbol,
                    "token1_decimals": token1_decimals,
                    "pair_symbol": f"{token0_symbol}-{token1_symbol}|{fee}",
                },
            )

        return {
            "token0": {
                "address": token0Addr,
                "name": token0_name,
                "symbol": token0_symbol,
                "decimals": token0_decimals,
            },
            "token1": {
                "address": token1Addr,
                "name": token1_name,
                "symbol": token1_symbol,
                "decimals": token1_decimals,
            },
            "pair": {
                "symbol": f"{token0_symbol}-{token1_symbol}|{fee}",
                "address": pair_address,
                "fee": fee,
            },
        }
    except Exception as err:
        # this will be retried in next cycle
        helper_logger.opt(exception=True).error(
            (
                f"RPC error while fetcing metadata for pair {pair_address},"
                f" error_msg:{err}"
            ),
        )
        raise err
    

async def get_token_eth_price_dict(
    token_address: str,
    token_decimals: int,
    from_block,
    to_block,
    redis_conn,
    rpc_helper: RpcHelper,
    ):
    """
    returns a dict of token price in eth for each block and stores it in redis
    """
    
    token_address = Web3.to_checksum_address(token_address)
    # check if cache exists
    token_eth_price_dict = dict()
    cached_token_price_dict = await redis_conn.zrangebyscore(
        name=uniswap_cached_block_height_token_eth_price.format(token_address),
        min=from_block,
        max=to_block,
    )
    if len(cached_token_price_dict) > 0:
        token_eth_price_dict = {
            int(json.loads(price)["blockHeight"]): json.loads(price)["price"]
            for price in cached_token_price_dict
        }
        
        return token_eth_price_dict

    # get token price function takes care of its own rate limit
    try: 
        # 1 token / x token
        token_eth_quote = await rpc_helper.batch_eth_call_on_block_range(
            abi_dict= get_contract_abi_dict(
                abi=quoter_1inch_contract_abi
            ),
            contract_address=worker_settings.contract_addresses.QUOTER_1INCH,
            from_block=from_block,
            to_block=to_block,
            function_name="getRateToEth",
            params=[
                token_address,
                True
            ],
            redis_conn=redis_conn,
        )
        block_counter = 0
        # parse token_eth_quote and store in dict
        if len(token_eth_quote) > 0:
            token_eth_quote = [(quote[0] * (10 ** (-36 + token_decimals))) for quote in token_eth_quote]
            for block_num in range(from_block, to_block + 1):
                token_eth_price_dict[block_num] = token_eth_quote[block_counter]
                block_counter += 1
            
                # cache price at height
        if len(token_eth_price_dict) > 0:

            redis_cache_mapping = {
                json.dumps({"blockHeight": height, "price": price}): int(
                    height,
                )
                for height, price in token_eth_price_dict.items()
            }

            await redis_conn.zadd(
                name=uniswap_cached_block_height_token_eth_price.format(
                    Web3.to_checksum_address(token_address),
                ),
                mapping=redis_cache_mapping,  # timestamp so zset do not ignore same height on multiple heights
            )

            return token_eth_price_dict

        else:
            return token_eth_price_dict
                


    except Exception as e:
        # TODO BETTER ERROR HANDLING
        helper_logger.debug(f"error while fetching token price for {token_address}, error_msg:{e}") 
        raise e
    




        

