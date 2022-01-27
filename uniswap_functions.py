from web3 import Web3
from dynaconf import settings
import logging.config
from proto_system_logging import config_logger_with_namespace
import os

web3 = Web3(Web3.HTTPProvider(settings.RPC.MATIC[0]))

#set logger scope
logging.root.setLevel(logging.getLevelName(os.environ.get("LOG_LEVEL", "DEBUG")))
logging.config.dictConfig(config_logger_with_namespace('PowerLoom|Uniswap|Helpers'))
logger = logging.getLogger('PowerLoom|Uniswap|Helpers')
logger.setLevel(logging.DEBUG)
logger.handlers = [logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]


quick_swap_uniswap_v2_factory_contract = web3.eth.contract(
    address=settings.CONTRACT_CONSTANTS.QUICK_SWAP_V2_FACTORY.ADDRESS, 
    abi=settings.CONTRACT_CONSTANTS.QUICK_SWAP_V2_FACTORY.ABI
)

quick_swap_uniswap_v2_pair_contract = web3.eth.contract(
    address=settings.CONTRACT_CONSTANTS.QUICK_SWAP_V2_PAIR.ADDRESS, 
    abi=settings.CONTRACT_CONSTANTS.QUICK_SWAP_V2_PAIR.ABI
)

# get allPairLength
def get_all_pair_length():
    return quick_swap_uniswap_v2_factory_contract.functions.allPairsLength().call()

# call allPair by index number
def getPairsByIndex(index):
    if not index:
        index = 0
    pair = quick_swap_uniswap_v2_factory_contract.functions.allPairs(index).call()
    print(f"pair address: {pair}")
    return pair

# get list of allPairs using allPairsLength
def get_all_pairs():
    all_pairs = []
    all_pair_length = get_all_pair_length()
    logger.debug(f"All pair length: {all_pair_length}, accumulating all pairs addresses, please wait...")
    for i in range(all_pair_length):
        all_pairs.append(getPairsByIndex(i))
    logger.debug(f"Fetched All pairs: {all_pairs}")
    return all_pairs


# call getReserves on pairs contract
def get_reserves():
    return quick_swap_uniswap_v2_pair_contract.functions.token0().call()

print(get_reserves())