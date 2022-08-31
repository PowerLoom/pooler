from redis_conn import provide_async_redis_conn_insta
from tenacity import retry, AsyncRetrying, stop_after_attempt, wait_random, wait_random_exponential, retry_if_exception_type
from rpc_helper import RPCException, batch_eth_call_on_block_range, contract_abi_dict, batch_eth_get_block
from rate_limiter import load_rate_limiter_scripts, check_rpc_rate_limit
from file_utils import read_json_file
import logging.config
import json
import math
from functools import partial
from dynaconf import settings
import asyncio
from redis import asyncio as aioredis
from web3 import Web3
from web3.middleware import geth_poa_middleware
from gnosis.eth import EthereumClient
from eth_utils import keccak
from web3._utils.events import get_event_data
from eth_abi.codec import ABICodec
from data_models import (
    trade_data, event_trade_data, epoch_event_trade_data
)
from datetime import datetime


from redis_keys import (
    uniswap_pair_contract_tokens_addresses, uniswap_pair_contract_tokens_data, uniswap_pair_cached_token_price,
    uniswap_pair_contract_V2_pair_data, uniswap_pair_cached_block_height_token_price,uniswap_eth_usd_price_zset,
    uniswap_tokens_pair_map, cached_block_details_at_height
)


ethereum_client = EthereumClient(settings.RPC.MATIC[0])
w3 = Web3(Web3.HTTPProvider(settings.RPC.MATIC[0]))
#TODO: test these middlewares with uniswap-v2 pooler instance
w3.middleware_onion.inject(geth_poa_middleware, layer=0, name="web3py_middleware")
ethereum_client.w3.middleware_onion.inject(geth_poa_middleware, layer=0, name="ethsafepy_middleware")
codec: ABICodec = w3.codec

###### Init Logger #####
logger = logging.getLogger('PowerLoom|UniswapHelpers')
logger.setLevel(logging.DEBUG)
logger.handlers = [logging.handlers.SocketHandler(host=settings.get('LOGGING_SERVER.HOST','localhost'), 
    port=settings.get('LOGGING_SERVER.PORT',logging.handlers.DEFAULT_TCP_LOGGING_PORT))]
########################


###### LOAD ABIs ######
pair_contract_abi = read_json_file(settings.UNISWAP_CONTRACT_ABIS.PAIR_CONTRACT, logger)
erc20_abi = read_json_file(settings.UNISWAP_CONTRACT_ABIS.erc20, logger)
router_contract_abi = read_json_file(settings.UNISWAP_CONTRACT_ABIS.ROUTER, logger)
uniswap_trade_events_abi = read_json_file(settings.UNISWAP_CONTRACT_ABIS.TRADE_EVENTS, logger)
factory_contract_abi = read_json_file(settings.UNISWAP_CONTRACT_ABIS.FACTORY, logger)
#######################


###### Init Uniswap V2 Core contract Objects #####
router_contract_obj = w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.IUNISWAP_V2_ROUTER),
    abi=router_contract_abi
)
factory_contract_obj = w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.IUNISWAP_V2_FACTORY),
    abi=factory_contract_abi
)
dai_eth_contract_obj = ethereum_client.w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.DAI_WETH_PAIR),
    abi=pair_contract_abi
)
usdc_eth_contract_obj = ethereum_client.w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDC_WETH_PAIR),
    abi=pair_contract_abi
)
eth_usdt_contract_obj = ethereum_client.w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDT_WETH_PAIR),
    abi=pair_contract_abi
)
##############################################


###### Constants #######
UNISWAP_TRADE_EVENT_SIGS = {
    'Swap': "Swap(address,uint256,uint256,uint256,uint256,address)",
    'Mint': "Mint(address,uint256,uint256)",
    'Burn': "Burn(address,uint256,uint256,address)"
}
UNISWAP_EVENTS_ABI = {
    'Swap': usdc_eth_contract_obj.events.Swap._get_event_abi(),
    'Mint': usdc_eth_contract_obj.events.Mint._get_event_abi(),
    'Burn': usdc_eth_contract_obj.events.Burn._get_event_abi(),
}
tokens_decimals = {
    "USDT": 6,
    "DAI": 18,
    "USDC": 6,
    "WETH": 18
}
#######################



def get_maker_pair_data(prop):
    prop = prop.lower()
    if prop.lower() == "name":
        return "Maker"
    elif prop.lower() == "symbol":
        return "MKR"
    else:
        return "Maker"


async def get_pair_metadata(
    pair_address,
    loop: asyncio.AbstractEventLoop,
    redis_conn: aioredis.Redis,
    rate_limit_lua_script_shas
):
    """
        returns information on the tokens contained within a pair contract - name, symbol, decimals of token0 and token1
        also returns pair symbol by concatenating {token0Symbol}-{token1Symbol}
    """
    try:
        pair_address = Web3.toChecksumAddress(pair_address)

        # check if cache exist
        pair_token_addresses_cache, pair_tokens_data_cache = await asyncio.gather(
            redis_conn.hgetall(uniswap_pair_contract_tokens_addresses.format(pair_address)),
            redis_conn.hgetall(uniswap_pair_contract_tokens_data.format(pair_address))
        )

        # parse addresses cache or call eth rpc
        token0Addr = None
        token1Addr = None
        if pair_token_addresses_cache:
            token0Addr = Web3.toChecksumAddress(pair_token_addresses_cache[b"token0Addr"].decode('utf-8'))
            token1Addr = Web3.toChecksumAddress(pair_token_addresses_cache[b"token1Addr"].decode('utf-8'))
        else:
            pair_contract_obj = w3.eth.contract(
                address=Web3.toChecksumAddress(pair_address),
                abi=pair_contract_abi
            )
            await check_rpc_rate_limit(
                redis_conn=redis_conn, request_payload={"pair_address": pair_address},
                error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get_pair_metadata fn"},
                logger=logger, rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1
            )
            token0Addr, token1Addr = ethereum_client.batch_call([
                pair_contract_obj.functions.token0(),
                pair_contract_obj.functions.token1()
            ])

            await redis_conn.hset(
                name=uniswap_pair_contract_tokens_addresses.format(pair_address),
                mapping={
                    'token0Addr': token0Addr,
                    'token1Addr': token1Addr
                }
            )

        # token0 contract
        token0 = w3.eth.contract(
            address=Web3.toChecksumAddress(token0Addr),
            abi=erc20_abi
        )
        # token1 contract
        token1 = w3.eth.contract(
            address=Web3.toChecksumAddress(token1Addr),
            abi=erc20_abi
        )

        # parse token data cache or call eth rpc
        if pair_tokens_data_cache:
            token0_decimals = pair_tokens_data_cache[b"token0_decimals"].decode('utf-8')
            token1_decimals = pair_tokens_data_cache[b"token1_decimals"].decode('utf-8')
            token0_symbol = pair_tokens_data_cache[b"token0_symbol"].decode('utf-8')
            token1_symbol = pair_tokens_data_cache[b"token1_symbol"].decode('utf-8')
            token0_name = pair_tokens_data_cache[b"token0_name"].decode('utf-8')
            token1_name = pair_tokens_data_cache[b"token1_name"].decode('utf-8')
        else:
            tasks = list()

            #special case to handle maker token
            maker_token0 = None
            maker_token1 = None
            if(Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.MAKER) == Web3.toChecksumAddress(token0Addr)):
                token0_name = get_maker_pair_data('name')
                token0_symbol = get_maker_pair_data('symbol')
                maker_token0 = True
            else:
                tasks.append(token0.functions.name())
                tasks.append(token0.functions.symbol())
            tasks.append(token0.functions.decimals())


            if(Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.MAKER) == Web3.toChecksumAddress(token1Addr)):
                token1_name = get_maker_pair_data('name')
                token1_symbol = get_maker_pair_data('symbol')
                maker_token1 = True
            else:
                tasks.append(token1.functions.name())
                tasks.append(token1.functions.symbol())
            tasks.append(token1.functions.decimals())

            await check_rpc_rate_limit(
                redis_conn=redis_conn, request_payload={"pair_address": pair_address},
                error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get_pair_metadata fn"},
                logger=logger, rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1
            )
            if maker_token1:
                [token0_name, token0_symbol, token0_decimals, token1_decimals] = ethereum_client.batch_call(
                    tasks
                )
            elif maker_token0:
                [token0_decimals, token1_name, token1_symbol, token1_decimals] = ethereum_client.batch_call(
                    tasks
                )
            else:
                [
                    token0_name, token0_symbol, token0_decimals, token1_name, token1_symbol, token1_decimals
                ] = ethereum_client.batch_call(tasks)

            await redis_conn.hset(
                name=uniswap_pair_contract_tokens_data.format(pair_address),
                mapping={
                    "token0_name": token0_name,
                    "token0_symbol": token0_symbol,
                    "token0_decimals": token0_decimals,
                    "token1_name": token1_name,
                    "token1_symbol": token1_symbol,
                    "token1_decimals": token1_decimals,
                    "pair_symbol": f"{token0_symbol}-{token1_symbol}"
                }
            )

        return {
            'token0': {
                'address': token0Addr,
                'name': token0_name,
                'symbol': token0_symbol,
                'decimals': token0_decimals
            },
            'token1': {
                'address': token1Addr,
                'name': token1_name,
                'symbol': token1_symbol,
                'decimals': token1_decimals
            },
            'pair': {
                'symbol': f'{token0_symbol}-{token1_symbol}'
            }
        }
    except Exception as err:
        # this will be retried in next cycle
        logger.error(f"RPC error while fetcing metadata for pair {pair_address}, error_msg:{err}", exc_info=True)
        raise err

async def get_pair(
    factory_contract_obj,
    token0, token1,
    loop: asyncio.AbstractEventLoop,
    redis_conn: aioredis.Redis,
    rate_limit_lua_script_shas
):

    #check if pair cache exists
    pair_address_cache = await redis_conn.hget(
        uniswap_tokens_pair_map,
        f"{Web3.toChecksumAddress(token0)}-{Web3.toChecksumAddress(token1)}"
    )
    if pair_address_cache:
        pair_address_cache = pair_address_cache.decode('utf-8')
        return Web3.toChecksumAddress(pair_address_cache)

    # get pair from eth rpc
    pair_func = partial(factory_contract_obj.functions.getPair(
        Web3.toChecksumAddress(token0),
        Web3.toChecksumAddress(token1)
    ).call)
    await check_rpc_rate_limit(
        redis_conn=redis_conn, request_payload={"token0": token0, "token1": token1},
        error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get_pair fn"},
        logger=logger, rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1
    )
    pair = await loop.run_in_executor(func=pair_func, executor=None)

    # cache the pair address
    await redis_conn.hset(
        name=uniswap_tokens_pair_map,
        mapping={f"{Web3.toChecksumAddress(token0)}-{Web3.toChecksumAddress(token1)}": Web3.toChecksumAddress(pair)}
    )

    return pair


async def get_eth_price_usd(loop, from_block, to_block, redis_conn: aioredis.Redis, rate_limit_lua_script_shas={}):
    """
        returns the price of eth in usd at a given block height
    """

    try:
        eth_price_usd_dict = dict()
        redis_cache_mapping = dict()

        if from_block != 'latest' and to_block != 'latest':
            cached_price_dict = await redis_conn.zrangebyscore(
                name=uniswap_eth_usd_price_zset,
                min=int(from_block),
                max=int(to_block)
            )
            if cached_price_dict and len(cached_price_dict) == to_block - (from_block - 1):
                price_dict = {json.loads(price.decode('utf-8'))['blockHeight']: json.loads(price.decode('utf-8'))['price'] for price in cached_price_dict}
                return price_dict


        # fetch metadata to find order of each token in given pairs
        dai_eth_pair_metadata, usdc_eth_pair_metadata, usdt_eth_pair_metadata = await asyncio.gather(
            get_pair_metadata(
                pair_address=settings.CONTRACT_ADDRESSES.DAI_WETH_PAIR,
                loop=loop,
                redis_conn=redis_conn,
                rate_limit_lua_script_shas=rate_limit_lua_script_shas
            ),
            get_pair_metadata(
                pair_address=settings.CONTRACT_ADDRESSES.USDC_WETH_PAIR,
                loop=loop,
                redis_conn=redis_conn,
                rate_limit_lua_script_shas=rate_limit_lua_script_shas
            ),
            get_pair_metadata(
                pair_address=settings.CONTRACT_ADDRESSES.USDT_WETH_PAIR,
                loop=loop,
                redis_conn=redis_conn,
                rate_limit_lua_script_shas=rate_limit_lua_script_shas
            )
        )
        # check if stable it token0 or token1 
        dai_token_order = 0 if Web3.toChecksumAddress(dai_eth_pair_metadata['token0']['address']) == Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.DAI) else 1
        usdc_token_order = 0 if Web3.toChecksumAddress(usdc_eth_pair_metadata['token0']['address']) == Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDC) else 1
        usdt_token_order = 0 if Web3.toChecksumAddress(usdt_eth_pair_metadata['token0']['address']) == Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDT) else 1


        # we are making single batch call here:
        await check_rpc_rate_limit(
            redis_conn=redis_conn, request_payload={"from_block": from_block, "to_block": to_block},
            error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get eth usd price fn"},
            logger=logger, rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1
        )

        # create dictionary of ABI {function_name -> {signature, abi, input, output}}
        pair_abi_dict = contract_abi_dict(pair_contract_abi)
        
        ## NOTE: We can further optimize below call by batching them all, but that would be a large batch call for RPC node
        dai_eth_pair_reserves_list = batch_eth_call_on_block_range(
            abi_dict=pair_abi_dict, 
            function_name='getReserves', 
            contract_address=settings.CONTRACT_ADDRESSES.DAI_WETH_PAIR, 
            from_block=from_block, 
            to_block=to_block
        )
        
        usdc_eth_pair_reserves_list = batch_eth_call_on_block_range(
            abi_dict=pair_abi_dict, 
            function_name='getReserves', 
            contract_address=settings.CONTRACT_ADDRESSES.USDC_WETH_PAIR, 
            from_block=from_block, 
            to_block=to_block
        )
        eth_usdt_pair_reserves_list = batch_eth_call_on_block_range(
            abi_dict=pair_abi_dict, 
            function_name='getReserves', 
            contract_address=settings.CONTRACT_ADDRESSES.USDT_WETH_PAIR, 
            from_block=from_block, 
            to_block=to_block
        )

        block_count = 0
        for block_num in range(from_block, to_block + 1):
            dai_eth_pair_dai_reserve = dai_eth_pair_reserves_list[block_count][dai_token_order]/10**tokens_decimals["DAI"]
            dai_eth_pair_eth_reserve = dai_eth_pair_reserves_list[block_count][1 - dai_token_order]/10**tokens_decimals["WETH"]
            dai_price = dai_eth_pair_dai_reserve / dai_eth_pair_eth_reserve

            usdc_eth_pair_usdc_reserve = usdc_eth_pair_reserves_list[block_count][usdc_token_order]/10**tokens_decimals["USDC"]
            usdc_eth_pair_eth_reserve = usdc_eth_pair_reserves_list[block_count][1 - usdc_token_order]/10**tokens_decimals["WETH"]
            usdc_price = usdc_eth_pair_usdc_reserve / usdc_eth_pair_eth_reserve

            usdt_eth_pair_usdt_reserve = eth_usdt_pair_reserves_list[block_count][usdt_token_order]/10**tokens_decimals["USDT"]
            usdt_eth_pair_eth_reserve = eth_usdt_pair_reserves_list[block_count][1 - usdt_token_order]/10**tokens_decimals["WETH"]
            usdt_price = usdt_eth_pair_usdt_reserve / usdt_eth_pair_eth_reserve

            total_eth_liquidity = dai_eth_pair_eth_reserve + usdc_eth_pair_eth_reserve + usdt_eth_pair_eth_reserve

            daiWeight = dai_eth_pair_eth_reserve / total_eth_liquidity
            usdcWeight = usdc_eth_pair_eth_reserve / total_eth_liquidity
            usdtWeight = usdt_eth_pair_eth_reserve / total_eth_liquidity

            eth_price_usd = daiWeight * dai_price + usdcWeight * usdc_price + usdtWeight * usdt_price

            eth_price_usd_dict[block_num] = float(eth_price_usd)
            redis_cache_mapping[json.dumps({ 'blockHeight': block_num, 'price': float(eth_price_usd)})] = int(block_num)

        # cache price at height
        if from_block != 'latest' and to_block != 'latest':
            await asyncio.gather(
                redis_conn.zadd(
                    name=uniswap_eth_usd_price_zset,
                    mapping=redis_cache_mapping
                ),
                redis_conn.zremrangebyscore(
                    name=uniswap_eth_usd_price_zset,
                    min=0,
                    max= int(from_block) - settings.EPOCH.HEIGHT * 4
                )
            )

        return eth_price_usd_dict

    except Exception as err:
        logger.error(f"RPC ERROR failed to fetch ETH price, error_msg:{err}")
        raise err

async def get_token_pair_price_and_white_token_reserves(
    pair_address, 
    from_block, 
    to_block, 
    pair_metadata, 
    white_token, 
    redis_conn,
    rate_limit_lua_script_shas
):
    """
    Function to get:
    1. token price based on pair reserves of both token: token0Price = token1Price/token0Price
    2. whitelisted token reserves

    We can write different function for each value, but to optimize we are reusing reserves value
    """
    token_price_dict = dict()
    white_token_reserves_dict = dict()

    # we are making single batch call here:
    await check_rpc_rate_limit(
        redis_conn=redis_conn, request_payload={"from_block": from_block, "to_block": to_block},
        error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get_token_pair_based_price fn"},
        logger=logger, rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1
    )

    # get white
    pair_abi_dict = contract_abi_dict(pair_contract_abi)
    pair_reserves_list = batch_eth_call_on_block_range(
        abi_dict=pair_abi_dict, 
        function_name='getReserves', 
        contract_address=pair_address, 
        from_block=from_block, 
        to_block=to_block
    )

    if len(pair_reserves_list) < to_block - (from_block - 1):
        raise RPCException(
            request={"from_block": from_block, "to_block": to_block},
            response=pair_reserves_list, underlying_exception=None,
            extra_info={'msg': f"Token pair based price RPC batch call error: {pair_reserves_list}"}
        )


    index = 0
    for block_num in range(from_block, to_block + 1):
        token_price = 0

        pair_reserve_token0 = pair_reserves_list[index][0]/10**int(pair_metadata['token0']["decimals"])
        pair_reserve_token1 = pair_reserves_list[index][1]/10**int(pair_metadata['token1']["decimals"])

        if float(pair_reserve_token0) == float(0) or float(pair_reserve_token1) == float(0):
            token_price_dict[block_num] = token_price
            white_token_reserves_dict[block_num] = 0
        elif Web3.toChecksumAddress(pair_metadata['token0']["address"]) == white_token:
            token_price_dict[block_num] = float(pair_reserve_token0 / pair_reserve_token1)
            white_token_reserves_dict[block_num] = pair_reserve_token0
        else:
            token_price_dict[block_num] = float(pair_reserve_token1 / pair_reserve_token0)
            white_token_reserves_dict[block_num] = pair_reserve_token1

        index += 1

    return token_price_dict, white_token_reserves_dict
    

async def get_token_derived_eth(
    from_block, 
    to_block, 
    white_token_metadata,
    redis_conn,
    rate_limit_lua_script_shas
):
    token_derived_eth_dict = dict()

    if Web3.toChecksumAddress(white_token_metadata['address']) == Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH):
        # set derived eth as 1 if token is weth
        for block_num in range(from_block, to_block + 1):
            token_derived_eth_dict[block_num] = 1
        
        return token_derived_eth_dict

    await check_rpc_rate_limit(
        redis_conn=redis_conn, request_payload={"from_block": from_block, "to_block": to_block},
        error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get_token_derived_eth fn"},
        logger=logger, rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1
    )

    # get white
    router_abi_dict = contract_abi_dict(router_contract_abi)
    token_derived_eth_list = batch_eth_call_on_block_range(
        abi_dict=router_abi_dict, 
        function_name='getAmountsOut', 
        contract_address=settings.CONTRACT_ADDRESSES.IUNISWAP_V2_ROUTER, 
        from_block=from_block, 
        to_block=to_block,
        params=[
            10 ** int(white_token_metadata['decimals']), 
            [
                Web3.toChecksumAddress(white_token_metadata['address']),
                Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH)
            ]
        ]
    )

    if len(token_derived_eth_list) < to_block - (from_block - 1):
        raise RPCException(
            request={"from_block": from_block, "to_block": to_block},
            response=token_derived_eth_list, underlying_exception=None,
            extra_info={'msg': f"Error: failed to fetch token derived eth RPC batch call error: {token_derived_eth_list}"}
        )

    index = 0
    for block_num in range(from_block, to_block + 1):
        if not token_derived_eth_list[index]:
            token_derived_eth_dict[block_num] = 0

        _, derivedEth = token_derived_eth_list[index][0]
        token_derived_eth_dict[block_num] = derivedEth/10**tokens_decimals["WETH"] if derivedEth !=0 else 0
        index += 1

    return token_derived_eth_dict
        


@retry(
    reraise=True,
    retry=retry_if_exception_type(RPCException),
    wait=wait_random_exponential(multiplier=1, max=10),
    stop=stop_after_attempt(settings.UNISWAP_FUNCTIONS.RETRIAL_ATTEMPTS)
)
async def get_token_price_in_block_range(
    token_metadata,
    from_block, to_block,
    loop: asyncio.AbstractEventLoop,
    redis_conn: aioredis.Redis,
    rate_limit_lua_script_shas=None,
    debug_log=True
):
    """
        returns the price of a token at a given block range
    """
    try:
        token_price_dict = dict()

        # check if cahce exist for given epoch
        if from_block != 'latest' and to_block != 'latest':
            cached_price_dict = await redis_conn.zrangebyscore(
                name=uniswap_pair_cached_block_height_token_price.format(Web3.toChecksumAddress(token_metadata['address'])),
                min=int(from_block),
                max=int(to_block)
            )
            if cached_price_dict and len(cached_price_dict) == to_block - (from_block - 1):
                price_dict = {json.loads(price.decode('utf-8'))['blockHeight']: json.loads(price.decode('utf-8'))['price'] for price in cached_price_dict}
                return price_dict

        if Web3.toChecksumAddress(token_metadata['address']) == Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.WETH):
            token_price_dict = await get_eth_price_usd(loop=loop, from_block=from_block, to_block=to_block, redis_conn=redis_conn, rate_limit_lua_script_shas=rate_limit_lua_script_shas)
        else:
            token_eth_price_dict = dict()

            for white_token in settings.UNISWAP_V2_WHITELIST:
                white_token = Web3.toChecksumAddress(white_token)
                pairAddress = await get_pair(
                    factory_contract_obj, white_token, token_metadata['address'], 
                    loop, redis_conn, rate_limit_lua_script_shas
                )
                if pairAddress != "0x0000000000000000000000000000000000000000":
                    new_pair_metadata = await get_pair_metadata(
                        pair_address=pairAddress,
                        loop=loop,
                        redis_conn=redis_conn,
                        rate_limit_lua_script_shas=rate_limit_lua_script_shas
                    )
                    white_token_metadata = new_pair_metadata["token0"] if white_token == new_pair_metadata["token0"]["address"] else new_pair_metadata["token1"]

                    white_token_price_dict, white_token_reserves_dict = await get_token_pair_price_and_white_token_reserves(
                        pair_address=pairAddress, from_block=from_block, to_block=to_block,
                        pair_metadata=new_pair_metadata, white_token=white_token, redis_conn=redis_conn,
                        rate_limit_lua_script_shas=rate_limit_lua_script_shas
                    )
                    white_token_derived_eth_dict = await get_token_derived_eth(
                        from_block=from_block, to_block=to_block, white_token_metadata=white_token_metadata, 
                        redis_conn=redis_conn, rate_limit_lua_script_shas=rate_limit_lua_script_shas
                    )

                    less_than_minimum_liquidity = False
                    for block_num in range(from_block, to_block + 1):

                        white_token_reserves = white_token_reserves_dict.get(block_num) * white_token_derived_eth_dict.get(block_num)
                        
                        # ignore if reservers are less than threshold
                        if white_token_reserves < 1:
                            less_than_minimum_liquidity = True
                            break
                        
                        # else store eth price in dictionary
                        token_eth_price_dict[block_num] = white_token_price_dict.get(block_num) * white_token_derived_eth_dict.get(block_num)

                    # if reserves are less than threshold then try next whitelist token pair
                    if less_than_minimum_liquidity:
                        continue
                    
                    break
            
            if len(token_eth_price_dict) > 0:
                eth_usd_price_dict = await get_eth_price_usd(loop=loop, from_block=from_block, to_block=to_block, redis_conn=redis_conn, rate_limit_lua_script_shas=rate_limit_lua_script_shas)
                for block_num in range(from_block, to_block + 1):
                    token_price_dict[block_num] = token_eth_price_dict.get(block_num) * eth_usd_price_dict.get(block_num)

            if debug_log:
                logger.debug(f"{token_metadata['symbol']}: price is {token_price_dict} | its eth price is {token_eth_price_dict}")

        # cache price at height
        if from_block != 'latest' and to_block != 'latest' and len(token_price_dict) > 0:
            redis_cache_mapping = {json.dumps({ 'blockHeight': height, 'price': price }): int(height) for height, price in token_price_dict.items()}
            
            await redis_conn.zadd(
                name=uniswap_pair_cached_block_height_token_price.format(Web3.toChecksumAddress(token_metadata['address'])),
                mapping=redis_cache_mapping # timestamp so zset do not ignore same height on multiple heights
            )

        return token_price_dict

    except Exception as err:
        raise RPCException(request={"contract": token_metadata['address'], "from_block": from_block, "to_block": to_block},
            response={}, underlying_exception=None,
            extra_info={'msg': f"rpc error: {str(err)}"}) from err



@retry(
    reraise=True,
    retry=retry_if_exception_type(RPCException),
    wait=wait_random_exponential(multiplier=1, max=10),
    stop=stop_after_attempt(settings.UNISWAP_FUNCTIONS.RETRIAL_ATTEMPTS)
)
async def get_block_details_in_range(
    redis_conn: aioredis.Redis,
    from_block,
    to_block,
    rate_limit_lua_script_shas=None
):
    """
        Fetch block-details for a range of block number or a single block

    """
    try:
        
        if from_block != 'latest' and to_block != 'latest':
            cached_details = await redis_conn.zrangebyscore(
                name=cached_block_details_at_height,
                min=int(from_block),
                max=int(to_block)
            )
            
            # check if we have cached value for each block number
            if cached_details and len(cached_details) == to_block - (from_block - 1):
                cached_details = {json.loads(block_detail.decode('utf-8'))['number']: json.loads(block_detail.decode('utf-8')) for block_detail in cached_details}
                return cached_details


        await check_rpc_rate_limit(
            redis_conn=redis_conn, request_payload={ "from_block": from_block, "to_block": to_block},
            error_msg={'msg': "exhausted_api_key_rate_limit inside get_block_details_in_range"},
            logger=logger, rate_limit_lua_script_shas=rate_limit_lua_script_shas
        )
        rpc_batch_block_details = batch_eth_get_block(from_block, to_block)
        rpc_batch_block_details = rpc_batch_block_details if rpc_batch_block_details else []
                
        block_details_dict = dict()
        redis_cache_mapping = dict()
        
        block_num = from_block
        for block_details in rpc_batch_block_details:
            block_details = block_details.get('result')
            # right now we are just storing timestamp out of all block details, 
            # edit this if you want to store something else 
            block_details = {
                "timestamp": int(block_details.get('timestamp', None), 16),
                "number": int(block_details.get('number', None), 16)
            }

            block_details_dict[block_num] = block_details
            redis_cache_mapping[json.dumps(block_details)] = int(block_num)
            block_num+=1
    

        # add new block details and prune all block details older than latest 3 epochs
        if from_block != 'latest' and to_block != 'latest':
            await asyncio.gather(
                redis_conn.zadd(
                    name=cached_block_details_at_height,
                    mapping=redis_cache_mapping
                ),
                redis_conn.zremrangebyscore(
                    name=cached_block_details_at_height,
                    min=0,
                    max=int(from_block) - settings.EPOCH.HEIGHT * 3
                )
            )

        return block_details_dict

    except Exception as err:
        raise RPCException(request={"from_block": from_block, "to_block": to_block},
            response={}, underlying_exception=None,
            extra_info={'msg': f"block details in range rpc error: {str(err)}"}) from err

@provide_async_redis_conn_insta
@retry(
    reraise=True,
    retry=retry_if_exception_type(RPCException),
    wait=wait_random_exponential(multiplier=1, max=10),
    stop=stop_after_attempt(settings.UNISWAP_FUNCTIONS.RETRIAL_ATTEMPTS)
)
async def get_pair_reserves(
    loop: asyncio.AbstractEventLoop,
    rate_limit_lua_script_shas: dict,
    pair_address,
    from_block,
    to_block,
    redis_conn: aioredis.Redis=None,
    fetch_timestamp=False
):
    try:
        logger.debug(f"Starting pair total reserves query for: {pair_address}")
        if not rate_limit_lua_script_shas:
            rate_limit_lua_script_shas = await load_rate_limiter_scripts(redis_conn)
        pair_address = Web3.toChecksumAddress(pair_address)

        
        if fetch_timestamp:
            try:
                block_details_dict = await get_block_details_in_range(redis_conn, from_block, to_block, rate_limit_lua_script_shas)
            except Exception as err:
                logger.error('Error attempting to get block details of block-range %s-%s: %s, retrying again', from_block, to_block, err, exc_info=True)
                raise err
        else:
            block_details_dict = dict()

        pair_per_token_metadata = await get_pair_metadata(
            pair_address=pair_address,
            loop=loop,
            redis_conn=redis_conn,
            rate_limit_lua_script_shas=rate_limit_lua_script_shas
        )

        logger.debug(f"total pair reserves fetched block details for epoch for: {pair_address}")

        token0_price_map, token1_price_map = await asyncio.gather(
            get_token_price_in_block_range(
                token_metadata=pair_per_token_metadata['token0'], from_block=from_block, to_block=to_block,
                loop=loop, redis_conn=redis_conn, rate_limit_lua_script_shas=rate_limit_lua_script_shas, debug_log=False
            ),
            get_token_price_in_block_range(
                token_metadata=pair_per_token_metadata['token1'], from_block=from_block, to_block=to_block,
                loop=loop, redis_conn=redis_conn, rate_limit_lua_script_shas=rate_limit_lua_script_shas, debug_log=False
            )
        )

        logger.debug(f"Total reserves fetched token prices for: {pair_address}")

        # create dictionary of ABI {function_name -> {signature, abi, input, output}}
        pair_abi_dict = contract_abi_dict(pair_contract_abi)
        async for attempt in AsyncRetrying(reraise=True, stop=stop_after_attempt(3), wait=wait_random(1, 2)):
            with attempt:
                # get token price function takes care of its own rate limit
                await check_rpc_rate_limit(
                    redis_conn=redis_conn, request_payload={"contract": pair_address, "from_block": from_block, "to_block": to_block},
                    error_msg={'msg': "exhausted_api_key_rate_limit inside get_pair_reserves"},
                    logger=logger, rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1
                )
                reserves_array = batch_eth_call_on_block_range(
                    abi_dict=pair_abi_dict, 
                    function_name='getReserves', 
                    contract_address=pair_address, 
                    from_block=from_block, 
                    to_block=to_block
                )
                if reserves_array:
                    break
            
        logger.debug(f"Total reserves fetched getReserves results: {pair_address}")

        token0_decimals = pair_per_token_metadata['token0']['decimals']
        token1_decimals = pair_per_token_metadata['token1']['decimals']

        pair_reserves_arr = dict()
        block_count = 0
        for block_num in range(from_block, to_block + 1):  
            token0Amount = reserves_array[block_count][0] / 10 ** int(token0_decimals)
            token1Amount = reserves_array[block_count][1] / 10 ** int(token1_decimals)

            token0USD = token0Amount * token0_price_map.get(block_num, 0)
            token1USD = token1Amount * token1_price_map.get(block_num, 0)

            current_block_details = block_details_dict.get(block_num, None)
            timestamp = current_block_details.get('timestamp', None) if current_block_details else None

            pair_reserves_arr[block_num] = {
                'token0': token0Amount,
                'token1': token1Amount,
                'token0USD': token0USD,
                'token1USD': token1USD,
                'timestamp': timestamp
            }
            block_count+=1

        logger.debug(f"Calculated pair total reserves for epoch-range: {from_block} - {to_block} | pair_contract: {pair_address}")
        return pair_reserves_arr
    except Exception as exc:
        logger.error("error at get_pair_reserves fn, retrying..., error_msg: %s", exc, exc_info=True)
        raise RPCException(request={"contract": pair_address, "from_block": from_block, "to_block": to_block},
            response={}, underlying_exception=None,
            extra_info={'msg': f"Error: get_pair_reserves error_msg: {str(exc)}"}) from exc
            


def get_event_sig_and_abi():
    event_sig = ['0x' + keccak(text=sig).hex() for name, sig in UNISWAP_TRADE_EVENT_SIGS.items()]
    event_abi = {'0x' + keccak(text=sig).hex(): UNISWAP_EVENTS_ABI.get(name, 'incorrect event name') for name, sig in UNISWAP_TRADE_EVENT_SIGS.items()}
    return event_sig, event_abi


def get_events_logs(contract_address, toBlock, fromBlock, topics, event_abi):
    event_log = w3.eth.get_logs({
        'address': Web3.toChecksumAddress(contract_address),
        'toBlock': toBlock,
        'fromBlock': fromBlock,
        'topics': topics
    })

    all_events = []
    for log in event_log:
        abi = event_abi.get(log.topics[0].hex(), "") 
        evt = get_event_data(codec, abi, log)
        all_events.append(evt)

    return all_events


def extract_trade_volume_log(event_name, log, pair_per_token_metadata, token0_price_map, token1_price_map, block_details_dict):
    token0_swapped = 0
    token1_swapped = 0
    token0_swapped_usd = 0
    token1_swapped_usd = 0
    log_args = log.args        

    def token_native_and_usd_amount(token, token_type, token_price_map):
        if log.args.get(token_type) <= 0:
            return 0, 0

        token_amount = log.args.get(token_type) / 10 ** int(pair_per_token_metadata[token]['decimals'])
        token_usd_amount = token_amount * token_price_map.get(log.get('blockNumber'), 0)
        return token_amount, token_usd_amount

    if event_name == 'Swap':
        
        amount0In, amount0In_usd = token_native_and_usd_amount(
            token='token0', token_type='amount0In', token_price_map=token0_price_map
        )
        amount0Out, amount0Out_usd = token_native_and_usd_amount(
            token='token0', token_type='amount0Out', token_price_map=token0_price_map
        )
        amount1In, amount1In_usd = token_native_and_usd_amount(
            token='token1', token_type='amount1In', token_price_map=token1_price_map
        )
        amount1Out, amount1Out_usd = token_native_and_usd_amount(
            token='token1', token_type='amount1Out', token_price_map=token1_price_map
        )
        
        token0_amount = abs(amount0Out - amount0In)
        token1_amount = abs(amount1Out - amount1In)

        token0_amount_usd = abs(amount0Out_usd - amount0In_usd)
        token1_amount_usd = abs(amount1Out_usd - amount1In_usd)


    elif event_name == 'Mint' or event_name == 'Burn':
        token0_amount, token0_amount_usd = token_native_and_usd_amount(
            token='token0', token_type='amount0', token_price_map=token0_price_map
        )
        token1_amount, token1_amount_usd = token_native_and_usd_amount(
            token='token1', token_type='amount1', token_price_map=token1_price_map
        )
        

    trade_volume_usd = 0
    trade_fee_usd = 0
    
    
    block_details = block_details_dict.get(int(log.get('blockNumber', 0)), {})
    log = json.loads(Web3.toJSON(log))
    log["token0_amount"] = token0_amount
    log["token1_amount"] = token1_amount
    log["timestamp"] = block_details.get("timestamp", "")
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
        trade_fee_usd = token1_amount_usd  * 0.003 if token1_amount_usd else token0_amount_usd * 0.003 # uniswap LP fee rate

        #set final usd amount for swap
        log["trade_amount_usd"] = trade_volume_usd

        return trade_data(
            totalTradesUSD=trade_volume_usd,
            totalFeeUSD=trade_fee_usd,
            token0TradeVolume=token0_amount,
            token1TradeVolume=token1_amount,
            token0TradeVolumeUSD=token0_amount_usd,
            token1TradeVolumeUSD=token1_amount_usd
        ), log


    trade_volume_usd = token0_amount_usd + token1_amount_usd

    #set final usd amount for other events
    log["trade_amount_usd"] = trade_volume_usd

    return trade_data(
        totalTradesUSD=trade_volume_usd,
        totalFeeUSD=0.0,
        token0TradeVolume=token0_amount,
        token1TradeVolume=token1_amount,
        token0TradeVolumeUSD=token0_amount_usd,
        token1TradeVolumeUSD=token1_amount_usd
    ), log

# asynchronously get trades on a pair contract
@provide_async_redis_conn_insta
@retry(
    reraise=True,
    retry=retry_if_exception_type(RPCException),
    wait=wait_random_exponential(multiplier=1, max=10),
    stop=stop_after_attempt(settings.UNISWAP_FUNCTIONS.RETRIAL_ATTEMPTS)
)
async def get_pair_trade_volume(
    ev_loop: asyncio.AbstractEventLoop,
    rate_limit_lua_script_shas: dict,
    pair_address,
    from_block,
    to_block,
    redis_conn: aioredis.Redis=None,
    fetch_timestamp=True
):
    try:
        pair_address = Web3.toChecksumAddress(pair_address)
        block_details_dict = dict()
   
        if fetch_timestamp:
            try:
                block_details_dict = await get_block_details_in_range(redis_conn, from_block, to_block, rate_limit_lua_script_shas)
            except Exception as err:
                logger.error('Error attempting to get block details of to_block %s: %s, retrying again', to_block, err, exc_info=True)
                raise err

        pair_per_token_metadata = await get_pair_metadata(
            pair_address=pair_address,
            loop=ev_loop,
            redis_conn=redis_conn,
            rate_limit_lua_script_shas=rate_limit_lua_script_shas
        )
        token0_price_map, token1_price_map = await asyncio.gather(
            get_token_price_in_block_range(
                token_metadata=pair_per_token_metadata['token0'], from_block=from_block, to_block=to_block,
                loop=ev_loop, redis_conn=redis_conn, rate_limit_lua_script_shas=rate_limit_lua_script_shas, debug_log=False
            ),
            get_token_price_in_block_range(
                token_metadata=pair_per_token_metadata['token1'], from_block=from_block, to_block=to_block,
                loop=ev_loop, redis_conn=redis_conn, rate_limit_lua_script_shas=rate_limit_lua_script_shas, debug_log=False
            )
        )

        # fetch logs for swap, mint & burn
        event_sig, event_abi = get_event_sig_and_abi()
        pfunc_get_event_logs = partial(
            get_events_logs, **{
                'contract_address': pair_address,
                'toBlock': to_block,
                'fromBlock': from_block,
                'topics': [event_sig],
                'event_abi': event_abi
            }
        )
        await check_rpc_rate_limit(
            redis_conn=redis_conn, request_payload={"contract": pair_address, "to_block": to_block, "from_block": from_block},
            error_msg={'msg': "exhausted_api_key_rate_limit inside uniswap_functions get async trade volume"},
            logger=logger, rate_limit_lua_script_shas=rate_limit_lua_script_shas, limit_incr_by=1
        )
        events_log = await ev_loop.run_in_executor(func=pfunc_get_event_logs, executor=None)

        # group logs by txHashs ==> {txHash: [logs], ...}
        grouped_by_tx = dict()
        [grouped_by_tx[log.transactionHash.hex()].append(log) if log.transactionHash.hex() in grouped_by_tx else grouped_by_tx.update({log.transactionHash.hex(): [log]}) for log in events_log]
        
        
        # init data models with empty/0 values
        epoch_results = epoch_event_trade_data(
            Swap=event_trade_data(logs=[], trades=trade_data(
                totalTradesUSD=float(),
                totalFeeUSD=float(),
                token0TradeVolume=float(),
                token1TradeVolume=float(),
                token0TradeVolumeUSD=float(),
                token1TradeVolumeUSD=float(),
                recent_transaction_logs=list()
            )),
            Mint=event_trade_data(logs=[], trades=trade_data(
                totalTradesUSD=float(),
                totalFeeUSD=float(),
                token0TradeVolume=float(),
                token1TradeVolume=float(),
                token0TradeVolumeUSD=float(),
                token1TradeVolumeUSD=float(),
                recent_transaction_logs=list()
            )),
            Burn=event_trade_data(logs=[], trades=trade_data(
                totalTradesUSD=float(),
                totalFeeUSD=float(),
                token0TradeVolume=float(),
                token1TradeVolume=float(),
                token0TradeVolumeUSD=float(),
                token1TradeVolumeUSD=float(),
                recent_transaction_logs=list()
            )),
            Trades=trade_data(
                totalTradesUSD=float(),
                totalFeeUSD=float(),
                token0TradeVolume=float(),
                token1TradeVolume=float(),
                token0TradeVolumeUSD=float(),
                token1TradeVolumeUSD=float(),
                recent_transaction_logs=list()
            )
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
                recent_transaction_logs=list()
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
                    block_details_dict=block_details_dict
                )

                if log.event == "Swap":
                    epoch_results.Swap.logs.append(processed_log)
                    epoch_results.Swap.trades += trades_result
                    tx_hash_trades += trades_result # swap in single txHash should be added
                
                elif log.event == "Mint":
                    epoch_results.Mint.logs.append(processed_log)
                    epoch_results.Mint.trades += trades_result
                    tx_hash_trades += trades_result # Mint in identical txHash should be added
                
                elif log.event == "Burn":
                    epoch_results.Burn.logs.append(processed_log)
                    epoch_results.Burn.trades += trades_result
                    
                    # Check if enough Mint amount exist that we can "substract" Burn events, else "add" the Burn events in a identical txHash
                    if epoch_results.Mint.trades.totalTradesUSD >= math.ceil(trades_result.totalTradesUSD):
                        tx_hash_trades -= trades_result
                    else:
                        tx_hash_trades += trades_result

            # At the end of txHash logs we must normalize trade values, so it don't affect result of other txHash logs
            epoch_results.Trades += abs(tx_hash_trades)

        epoch_trade_logs = epoch_results.dict()
        max_block_details = block_details_dict.get(to_block, {})
        max_block_timestamp = max_block_details.get('timestamp', None)
        epoch_trade_logs.update({'timestamp': max_block_timestamp})            
        return epoch_trade_logs
    except Exception as exc:
        logger.error("error at get_pair_trade_volume fn: %s", exc, exc_info=True)
        raise RPCException(request={"contract": pair_address, "fromBlock": from_block, "toBlock": to_block},
            response={}, underlying_exception=None,
            extra_info={'msg': f"error: get_pair_trade_volume, error_msg: {str(exc)}"}) from exc


if __name__ == '__main__':
    toBlock = 32513351 

    # loop = asyncio.get_event_loop()
    # rate_limit_lua_script_shas = dict()
    # start_time = datetime.now()
    # data = loop.run_until_complete(
    #     get_pair_reserves(
    #         loop=loop, 
    #         rate_limit_lua_script_shas=rate_limit_lua_script_shas, 
    #         pair_address='0x72cf5ee9ee918a529b25bbcb0372594008178535',
    #         from_block=32513509,
    #         to_block=32513583,
    #         fetch_timestamp=True
    #     )
    # )
    # end_time = datetime.now()

    # print(f"\n\n{data}\n")
    # print(f"time taken to fetch price in epoch range: {start_time} - {end_time}")
    
    
    # rate_limit_lua_script_shas = dict()
    # loop = asyncio.get_event_loop()
    # start_time = datetime.now()
    # data = loop.run_until_complete(
    #     get_pair_trade_volume(
    #         loop, 
    #         rate_limit_lua_script_shas, 
    #         '0x6e7a5fafcec6bb1e78bae2a1f0b612012bf14827', 
    #         from_block=toBlock-75,
    #         to_block=toBlock,
    #     )
    # )
    # end_time = datetime.now()
    # print(f"\n\n{data}\n")
    # print(f"time taken to fetch price in epoch range: {start_time} - {end_time}")
    
    pass
