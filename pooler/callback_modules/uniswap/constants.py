from dynaconf import settings
from utils.default_logger import logger
from utils.file_utils import read_json_file
from utils.rpc_helper import GLOBAL_WEB3_PROVIDER
from web3 import Web3

constants_logger = logger.bind(module='PowerLoom|Uniswap|Constants')


# LOAD ABIs
pair_contract_abi = read_json_file(settings.UNISWAP_CONTRACT_ABIS.PAIR_CONTRACT, constants_logger)
erc20_abi = read_json_file(settings.UNISWAP_CONTRACT_ABIS.erc20, constants_logger)
router_contract_abi = read_json_file(settings.UNISWAP_CONTRACT_ABIS.ROUTER, constants_logger)
uniswap_trade_events_abi = read_json_file(settings.UNISWAP_CONTRACT_ABIS.TRADE_EVENTS, constants_logger)
factory_contract_abi = read_json_file(settings.UNISWAP_CONTRACT_ABIS.FACTORY, constants_logger)


# CONSTANT WEB3 CLIENT
global_w3_client = GLOBAL_WEB3_PROVIDER['full_nodes'][0]


# Init Uniswap V2 Core contract Objects
router_contract_obj = global_w3_client['web3_client'].w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.IUNISWAP_V2_ROUTER),
    abi=router_contract_abi,
)
factory_contract_obj = global_w3_client['web3_client'].w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.IUNISWAP_V2_FACTORY),
    abi=factory_contract_abi,
)
dai_eth_contract_obj = global_w3_client['web3_client'].w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.DAI_WETH_PAIR),
    abi=pair_contract_abi,
)
usdc_eth_contract_obj = global_w3_client['web3_client'].w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDC_WETH_PAIR),
    abi=pair_contract_abi,
)
eth_usdt_contract_obj = global_w3_client['web3_client'].w3.eth.contract(
    address=Web3.toChecksumAddress(settings.CONTRACT_ADDRESSES.USDT_WETH_PAIR),
    abi=pair_contract_abi,
)


# FUNCTION SIGNATURES and OTHER CONSTANTS
UNISWAP_TRADE_EVENT_SIGS = {
    'Swap': 'Swap(address,uint256,uint256,uint256,uint256,address)',
    'Mint': 'Mint(address,uint256,uint256)',
    'Burn': 'Burn(address,uint256,uint256,address)',
}
UNISWAP_EVENTS_ABI = {
    'Swap': usdc_eth_contract_obj.events.Swap._get_event_abi(),
    'Mint': usdc_eth_contract_obj.events.Mint._get_event_abi(),
    'Burn': usdc_eth_contract_obj.events.Burn._get_event_abi(),
}
tokens_decimals = {
    'USDT': 6,
    'DAI': 18,
    'USDC': 6,
    'WETH': 18,
}
