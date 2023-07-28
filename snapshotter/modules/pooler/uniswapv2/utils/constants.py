from web3 import Web3

from ..settings.config import settings as worker_settings
from snapshotter.utils.default_logger import logger
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.rpc import RpcHelper

constants_logger = logger.bind(module='PowerLoom|Uniswap|Constants')
# Getting current node

rpc_helper = RpcHelper()
current_node = rpc_helper.get_current_node()

# LOAD ABIs
pair_contract_abi = read_json_file(
    worker_settings.uniswap_contract_abis.pair_contract,
    constants_logger,
)
erc20_abi = read_json_file(
    worker_settings.uniswap_contract_abis.erc20,
    constants_logger,
)
router_contract_abi = read_json_file(
    worker_settings.uniswap_contract_abis.router,
    constants_logger,
)
uniswap_trade_events_abi = read_json_file(
    worker_settings.uniswap_contract_abis.trade_events,
    constants_logger,
)
factory_contract_abi = read_json_file(
    worker_settings.uniswap_contract_abis.factory,
    constants_logger,
)


# Init Uniswap V2 Core contract Objects
router_contract_obj = current_node['web3_client'].eth.contract(
    address=Web3.toChecksumAddress(
        worker_settings.contract_addresses.iuniswap_v2_router,
    ),
    abi=router_contract_abi,
)
factory_contract_obj = current_node['web3_client'].eth.contract(
    address=Web3.toChecksumAddress(
        worker_settings.contract_addresses.iuniswap_v2_factory,
    ),
    abi=factory_contract_abi,
)
dai_eth_contract_obj = current_node['web3_client'].eth.contract(
    address=Web3.toChecksumAddress(
        worker_settings.contract_addresses.DAI_WETH_PAIR,
    ),
    abi=pair_contract_abi,
)
usdc_eth_contract_obj = current_node['web3_client'].eth.contract(
    address=Web3.toChecksumAddress(
        worker_settings.contract_addresses.USDC_WETH_PAIR,
    ),
    abi=pair_contract_abi,
)
eth_usdt_contract_obj = current_node['web3_client'].eth.contract(
    address=Web3.toChecksumAddress(
        worker_settings.contract_addresses.USDT_WETH_PAIR,
    ),
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
