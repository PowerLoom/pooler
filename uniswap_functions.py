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

#set logger scope
logging.root.setLevel(logging.getLevelName(os.environ.get("LOG_LEVEL", "DEBUG")))
logging.config.dictConfig(config_logger_with_namespace('PowerLoom|Uniswap|Helpers'))
logger = logging.getLogger('PowerLoom|Uniswap|Helpers')
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
def getPairsByIndex(index, semaphore=None):
    if not index:
        index = 0
    pair = quick_swap_uniswap_v2_factory_contract.functions.allPairs(index).call()
    print(f"{pair},")
    return pair

# get list of allPairs using allPairsLength
def get_all_pairs():
    all_pairs = []
    all_pair_length = get_all_pair_length()
    logger.debug(f"All pair length: {all_pair_length}, accumulating all pairs addresses, please wait...")
    print(f"All pair length: {all_pair_length}, accumulating all pairs addresses, please wait...")
    
    # declare semaphore and executor
    sem = threading.BoundedSemaphore(settings.UNISWAP_FUNCTIONS.THREADING_SEMAPHORE)
    with BoundedThreadPoolExecutor(max_workers=settings.UNISWAP_FUNCTIONS.SEMAPHORE_WORKERS) as executor:
        future_to_pairs_addr = {executor.submit(
            getPairsByIndex,
            index=index,
            semaphore=sem
        ): index for index in range(all_pair_length)}
    for future in as_completed(future_to_pairs_addr):
        pair_addr = future_to_pairs_addr[future]
        try:
            rj = future.result()
        except Exception as exc:
            print("future error: ", exc)
            logger.error(f"Error getting address of pair against index: {pair_addr}")
            logger.error(exc, exc_info=True)
            continue
        else:
            if rj:
                all_pairs.append(rj)
            else:
                print(f"Skipping pair address at index: {pair_addr}")
                logger.debug(f"Skipping pair address at index: {pair_addr}")

    return all_pairs
                
    # for i in range(all_pair_length):
    #     all_pairs.append(getPairsByIndex(i))
    # logger.debug(f"Fetched All pairs: {all_pairs}")
    # return all_pairs


# get list of allPairs using allPairsLength and write to file
def get_all_pairs_and_write_to_file():
    try:
        all_pairs = get_all_pairs()
        if not os.path.exists('./static'):
            os.makedirs('./static')

        with open('./static/cached_pair_addresses.json', 'w') as f:
            json.dump(all_pairs, f)
        return all_pairs
    except Exception as e:
        logger.error(e, exc_info=True)
        raise e

# call getReserves on pairs contract
def get_reserves():
    return quick_swap_uniswap_v2_pair_contract.functions.getReserves().call()


print(get_all_pairs_and_write_to_file())