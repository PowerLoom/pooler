from web3 import Web3
from dynaconf import settings
import logging.config
from proto_system_logging import config_logger_with_namespace
import os
import json
from bounded_pool_executor import BoundedThreadPoolExecutor
import threading
from concurrent.futures import as_completed
from helper_functions import handle_failed_maticvigil_exception, acquire_threading_semaphore

web3 = Web3(Web3.HTTPProvider(settings.RPC.MATIC[0]))

logger = logging.getLogger('PowerLoom|UniswapHelpers')
logger.setLevel(logging.DEBUG)
logger.handlers = [logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]


def read_json_file(file_path: str):
    """Read given json file and return its content as a dictionary."""
    try:
        f_ = open(file_path, 'r')
    except Exception as e:
        logger.warning(f"Unable to open the {file_path} file")
        logger.error(e, exc_info=True)
        raise e
    else:
        logger.debug(f"Reading {file_path} file")
        json_data = json.loads(f_.read())
    return json_data


def instantiate_contracts():
    """Instantiate all contracts."""
    global quick_swap_uniswap_v2_factory_contract
    global quick_swap_uniswap_v2_pair_contract
    
    try:
        # intantiate UniswapV2Factory contract (using quick swap v2 factory address)
        quick_swap_uniswap_v2_factory_contract = web3.eth.contract(
            address=settings.CONTRACT_ADDRESSES.QUICK_SWAP_IUNISWAP_V2_FACTORY,
            abi=read_json_file('./abis/IUniswapV2Factory.json')
        )

        # intantiate UniswapV2Pair contract (using quick swap v2 pair address)
        quick_swap_uniswap_v2_pair_contract = web3.eth.contract(
            address=settings.CONTRACT_ADDRESSES.QUICK_SWAP_IUNISWAP_V2_PAIR, 
            abi=read_json_file('./abis/UniswapV2Pair.json')
        )

    except Exception as e:
        print(e)
        logger.error(e, exc_info=True)

#initiate all contracts
instantiate_contracts()


# get allPairLength
def get_all_pair_length():
    return quick_swap_uniswap_v2_factory_contract.functions.allPairsLength().call()

# call allPair by index number
@acquire_threading_semaphore
def get_pair_by_index(index, semaphore=None):
    if not index:
        index = 0
    pair = quick_swap_uniswap_v2_factory_contract.functions.allPairs(index).call()
    return pair


# get list of allPairs using allPairsLength
def get_all_pairs():
    all_pairs = []
    all_pair_length = get_all_pair_length()
    logger.debug(f"All pair length: {all_pair_length}, accumulating all pairs addresses, please wait...")

    # declare semaphore and executor
    sem = threading.BoundedSemaphore(settings.UNISWAP_FUNCTIONS.THREADING_SEMAPHORE)
    with BoundedThreadPoolExecutor(max_workers=settings.UNISWAP_FUNCTIONS.SEMAPHORE_WORKERS) as executor:
        future_to_pairs_addr = {executor.submit(
            get_pair_by_index,
            index=index,
            semaphore=sem
        ): index for index in range(all_pair_length)}
    added = 0
    for future in as_completed(future_to_pairs_addr):
        pair_addr = future_to_pairs_addr[future]
        try:
            rj = future.result()
        except Exception as exc:
            logger.error(f"Error getting address of pair against index: {pair_addr}")
            logger.error(exc, exc_info=True)
            continue
        else:
            if rj:
                all_pairs.append(rj)
                added += 1
                if added % 1000 == 0:
                    logger.debug(f"Accumulated {added} pair addresses")
            else:
                logger.debug(f"Skipping pair address at index: {pair_addr}")
    logger.debug(f"Cached a total {added} pair addresses")
    return all_pairs


# get list of allPairs using allPairsLength and write to file
def get_all_pairs_and_write_to_file():
    try:
        all_pairs = get_all_pairs()
        if not os.path.exists('static/'):
            os.makedirs('static/')

        with open('static/cached_pair_addresses.json', 'w') as f:
            json.dump(all_pairs, f)
        return all_pairs
    except Exception as e:
        logger.error(e, exc_info=True)
        raise e


# call getReserves on pairs contract
def get_reserves():
    return quick_swap_uniswap_v2_pair_contract.functions.getReserves().call()


# TODO: 'asyncify' the web3 calls
# async limits rate limit check
# if rate limit checks out then we call
# introduce block height in get reserves
# reservers = pair.functions.getReserves().call()

# get liquidity of each token reserve
def get_liquidity_of_each_token_reserve(pair_address, block_identifier='latest'):
    logger.debug("Pair Data:")
    
    #pair contract
    pair = web3.eth.contract(
        address=pair_address, 
        abi=read_json_file(f"abis/UniswapV2Pair.json")
    )

    token0Addr = pair.functions.token0().call()
    token1Addr = pair.functions.token1().call()
    # async limits rate limit check
    # if rate limit checks out then we call
    # introduce block height in get reserves
    reservers = pair.functions.getReserves().call(block_identifier=block_identifier)
    logger.debug(f"Token0: {token0Addr}, Reservers: {reservers[0]}")
    logger.debug(f"Token1: {token1Addr}, Reservers: {reservers[1]}")
    

    #toke0 contract
    token0 = web3.eth.contract(
        address=token0Addr, 
        abi=read_json_file('abis/IERC20.json')
    )
    #toke1 contract
    token1 = web3.eth.contract(
        address=token1Addr, 
        abi=read_json_file('abis/IERC20.json')
    )

    token0_decimals = token0.functions.decimals().call()
    token1_decimals = token1.functions.decimals().call()

    
    logger.debug(f"Decimals of token1: {token1_decimals}, Decimals of token1: {token0_decimals}")
    logger.debug(f"reservers[0]/10**token0_decimals: {reservers[0]/10**token0_decimals}, reservers[1]/10**token1_decimals: {reservers[1]/10**token1_decimals}")

    return {"token0": reservers[0]/10**token0_decimals, "token1": reservers[1]/10**token1_decimals}

def get_pair(token0, token1):
    pair = quick_swap_uniswap_v2_factory_contract.functions.getPair(token0, token1).call()
    return pair
    


if __name__ == '__main__':
    
    #here instead of calling get pair we can directly use cached all pair addresses
    dai= "0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063"
    gns= "0xE5417Af564e4bFDA1c483642db72007871397896"
    pair_address = get_pair(dai, gns)
    logger.debug(f"Pair address : {pair_address}")
    logger.debug(get_liquidity_of_each_token_reserve(pair_address))

    #we can pass block_identifier=chain_height
    print(get_liquidity_of_each_token_reserve(pair_address, block_identifier=24265790))
