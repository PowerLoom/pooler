# Adapted from https://github.com/uniswap-python/uniswap-python
import functools
import json
import logging
import math
from collections import namedtuple
from typing import Any
from typing import cast
from typing import Dict
from typing import Generator
from typing import List
from typing import Sequence
from typing import Set
from typing import Tuple
from typing import TypeVar
from typing import Union

import lru
from eth_typing.evm import Address
from eth_typing.evm import ChecksumAddress
from hexbytes import HexBytes
from typing_extensions import ParamSpec
from web3 import Web3
from web3._utils.abi import map_abi_data
from web3._utils.normalizers import BASE_RETURN_NORMALIZERS
from web3.contract import Contract
from web3.exceptions import NameNotFound
from web3.middleware.cache import construct_simple_cache_middleware
from web3.types import Middleware
from web3.types import (  # noqa: F401
    RPCEndpoint,
)


AddressLike = Union[Address, ChecksumAddress]

T = TypeVar('T')
P = ParamSpec('P')


class InvalidToken(Exception):
    """Raised when an invalid token address is used."""

    def __init__(self, address: Any) -> None:
        Exception.__init__(self, f'Invalid token address: {address}')


class InsufficientBalance(Exception):
    """Raised when the account has insufficient balance for a transaction."""

    def __init__(self, had: int, needed: int) -> None:
        Exception.__init__(self, f'Insufficient balance. Had {had}, needed {needed}')


# look at web3/middleware/cache.py for reference
# RPC methods that will be cached inside _get_eth_simple_cache_middleware
SIMPLE_CACHE_RPC_WHITELIST = cast(
    Set[RPCEndpoint],
    {
        'eth_chainId',
    },
)

ETH_ADDRESS = '0x0000000000000000000000000000000000000000'
WETH_ADDRESS = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'

w3 = Web3(Web3.HTTPProvider('https://rpc-eth-lb.blockvigil.com/v1/******************'))

# see: https://chainid.network/chains/
_netid_to_name = {
    1: 'mainnet',
    3: 'ropsten',
    4: 'rinkeby',
    5: 'görli',
    10: 'optimism',
    42: 'kovan',
    56: 'binance',
    97: 'binance_testnet',
    137: 'polygon',
    100: 'xdai',
    250: 'fantom',
    42161: 'arbitrum',
    421611: 'arbitrum_testnet',
    1666600000: 'harmony_mainnet',
    1666700000: 'harmony_testnet',
}

_factory_contract_addresses_v1 = {
    'mainnet': '0xc0a47dFe034B400B47bDaD5FecDa2621de6c4d95',
    'ropsten': '0x9c83dCE8CA20E9aAF9D3efc003b2ea62aBC08351',
    'rinkeby': '0xf5D915570BC477f9B8D6C0E980aA81757A3AaC36',
    'kovan': '0xD3E51Ef092B2845f10401a0159B2B96e8B6c3D30',
    'görli': '0x6Ce570d02D73d4c384b46135E87f8C592A8c86dA',
}


# For v2 the address is the same on mainnet, Ropsten, Rinkeby, Görli, and Kovan
# https://uniswap.org/docs/v2/smart-contracts/factory
_factory_contract_addresses_v2 = {
    'mainnet': '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f',
    'ropsten': '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f',
    'rinkeby': '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f',
    'görli': '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f',
    'xdai': '0xA818b4F111Ccac7AA31D0BCc0806d64F2E0737D7',
    'binance': '0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73',
    'binance_testnet': '0x6725F303b657a9451d8BA641348b6761A6CC7a17',
    # SushiSwap on Harmony
    'harmony_mainnet': '0xc35DADB65012eC5796536bD9864eD8773aBc74C4',
    'harmony_testnet': '0xc35DADB65012eC5796536bD9864eD8773aBc74C4',
}

_router_contract_addresses_v2 = {
    'mainnet': '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D',
    'ropsten': '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D',
    'rinkeby': '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D',
    'görli': '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D',
    'xdai': '0x1C232F01118CB8B424793ae03F870aa7D0ac7f77',
    'binance': '0x10ED43C718714eb63d5aA57B78B54704E256024E',
    'binance_testnet': '0xD99D1c33F9fC3444f8101754aBC46c52416550D1',
    # SushiSwap on Harmony
    'harmony_mainnet': '0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506',
    'harmony_testnet': '0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506',
}

MAX_UINT_128 = (2**128) - 1

# Source: https://github.com/Uniswap/v3-core/blob/v1.0.0/contracts/libraries/TickMath.sol#L8-L11
MIN_TICK = -887272
MAX_TICK = -MIN_TICK

# Source: https://github.com/Uniswap/v3-core/blob/v1.0.0/contracts/UniswapV3Factory.sol#L26-L31
_tick_spacing = {100: 1, 500: 10, 3_000: 60, 10_000: 200}

# Derived from (MIN_TICK//tick_spacing) >> 8 and (MAX_TICK//tick_spacing) >> 8
_tick_bitmap_range = {100: (-3466, 3465), 500: (-347, 346), 3_000: (-58, 57), 10_000: (-18, 17)}

logger = logging.getLogger(__name__)


def _get_eth_simple_cache_middleware() -> Middleware:
    return construct_simple_cache_middleware(
        cache=functools.partial(lru.LRU, 256),  # type: ignore
        rpc_whitelist=SIMPLE_CACHE_RPC_WHITELIST,
    )


def _str_to_addr(s: Union[AddressLike, str]) -> Address:
    """Idempotent"""
    if isinstance(s, str):
        if s.startswith('0x'):
            return Address(bytes.fromhex(s[2:]))
        else:
            raise NameNotFound(f"Couldn't convert string '{s}' to AddressLike")
    else:
        return s


def _addr_to_str(a: AddressLike) -> str:
    if isinstance(a, bytes):
        # Address or  ChecksumAddress
        addr: str = Web3.to_checksum_address('0x' + bytes(a).hex())
        return addr
    elif isinstance(a, str) and a.startswith('0x'):
        addr = Web3.to_checksum_address(a)
        return addr

    raise NameNotFound(a)


def is_same_address(a1: Union[AddressLike, str], a2: Union[AddressLike, str]) -> bool:
    return _str_to_addr(a1) == _str_to_addr(a2)


def _validate_address(a: AddressLike) -> None:
    assert _addr_to_str(a)


def _load_abi(path: str) -> str:
    with open(path) as f:
        abi: str = json.load(f)
    return abi


# Batch contract function calls to speed up large on-chain data queries
def multicall(
    encoded_functions: Sequence[Tuple[ChecksumAddress, bytes]],
    output_types: Sequence[str],
) -> List[Any]:
    """
    Calls aggregate() on Uniswap Multicall2 contract

    Params
    ------
    encoded_functions : Sequence[Tuple[ChecksumAddress, bytes]]
        array of tuples containing address of contract and byte-encoded transaction data

    output_types: Sequence[str]
        array of solidity output types for decoding (e.g. uint256, bool, etc.)

    returns decoded results
    """
    params = [
        {'target': target, 'callData': callData}
        for target, callData in encoded_functions
    ]
    _, results = multicall2.functions.aggregate(params).call(
        block_identifier='latest',
    )
    decoded_results = [
        w3.codec.decode(output_types, multicall_result)
        for multicall_result in results
    ]
    normalized_results = [
        map_abi_data(BASE_RETURN_NORMALIZERS, output_types, decoded_result)
        for decoded_result in decoded_results
    ]
    return normalized_results


@functools.lru_cache()
def _load_contract(w3: Web3, abi_name: str, address: AddressLike) -> Contract:
    address = Web3.to_checksum_address(address)
    return w3.eth.contract(address=address, abi=_load_abi(abi_name))


def _load_contract_erc20(w3: Web3, address: AddressLike) -> Contract:
    return _load_contract(w3, 'pooler/static/abis/ERC20.json', address)


def _encode_path(token_in: AddressLike, route: List[Tuple[int, AddressLike]]) -> bytes:
    """
    Needed for multi-hop swaps in V3.

    https://github.com/Uniswap/uniswap-v3-sdk/blob/1a74d5f0a31040fec4aeb1f83bba01d7c03f4870/src/utils/encodeRouteToPath.ts
    """
    raise NotImplementedError


# Adapted from: https://github.com/Uniswap/v3-sdk/blob/main/src/utils/encodeSqrtRatioX96.ts
def encode_sqrt_ratioX96(amount_0: int, amount_1: int) -> int:
    numerator = amount_1 << 192
    denominator = amount_0
    ratioX192 = numerator // denominator
    return int(math.sqrt(ratioX192))


# Adapted from: https://github.com/tradingstrategy-ai/web3-ethereum-defi/blob/c3c68bc723d55dda0cc8252a0dadb534c4fdb2c5/eth_defi/uniswap_v3/utils.py#L77
def get_min_tick(fee: int) -> int:
    min_tick_spacing: int = _tick_spacing[fee]
    return -(MIN_TICK // -min_tick_spacing) * min_tick_spacing


def get_max_tick(fee: int) -> int:
    max_tick_spacing: int = _tick_spacing[fee]
    return (MAX_TICK // max_tick_spacing) * max_tick_spacing


def default_tick_range(fee: int) -> Tuple[int, int]:
    min_tick = get_min_tick(fee)
    max_tick = get_max_tick(fee)

    return min_tick, max_tick


def nearest_tick(tick: int, fee: int) -> int:
    min_tick, max_tick = default_tick_range(fee)
    assert (
        min_tick <= tick <= max_tick
    ), f'Provided tick is out of bounds: {(min_tick, max_tick)}'

    tick_spacing = _tick_spacing[fee]
    rounded_tick_spacing = round(tick / tick_spacing) * tick_spacing

    if rounded_tick_spacing < min_tick:
        return rounded_tick_spacing + tick_spacing
    elif rounded_tick_spacing > max_tick:
        return rounded_tick_spacing - tick_spacing
    else:
        return rounded_tick_spacing


def chunks(arr: Sequence[Any], n: int) -> Generator:
    for i in range(0, len(arr), n):
        yield arr[i: i + n]

#  Find maximum tick of the word at the largest index (wordPos) in the tickBitmap that contains an initialized tick


def get_max_tick_from_wordpos(
    wordPos: int, bitmap: str, tick_spacing: int, fee: int,
) -> int:
    compressed_tick = wordPos << 8
    _tick = compressed_tick * tick_spacing
    min_tick_in_word = nearest_tick(_tick, fee)
    max_tick_in_word = min_tick_in_word + (len(bitmap) * tick_spacing)
    return max_tick_in_word

# Find minimum tick of word at the smallest index (wordPos) in the tickBitmap that contains an initialized tick


def get_min_tick_from_wordpos(
    wordPos: int, tick_spacing: int, fee: int,
) -> int:
    compressed_tick = wordPos << 8
    _tick = compressed_tick * tick_spacing
    min_tick_in_word = nearest_tick(_tick, fee)
    return min_tick_in_word


def get_pool_immutables(pool: Contract) -> Dict:
    """
    Fetch on-chain pool data.
    """
    pool_immutables = {
        'factory': pool.functions.factory().call(),
        'token0': pool.functions.token0().call(),
        'token1': pool.functions.token1().call(),
        'fee': pool.functions.fee().call(),
        'tickSpacing': pool.functions.tickSpacing().call(),
        'maxLiquidityPerTick': pool.functions.maxLiquidityPerTick().call(),
    }

    print(pool_immutables)

    return pool_immutables


def get_pool_state(pool: Contract) -> Dict:
    """
    Fetch on-chain pool state.
    """
    liquidity = pool.functions.liquidity().call()
    slot = pool.functions.slot0().call()
    pool_state = {
        'liquidity': liquidity,
        'sqrtPriceX96': slot[0],
        'tick': slot[1],
        'observationIndex': slot[2],
        'observationCardinality': slot[3],
        'observationCardinalityNext': slot[4],
        'feeProtocol': slot[5],
        'unlocked': slot[6],
    }

    print(pool_state)

    return pool_state


multicall2_addr = _str_to_addr(
    '0x5BA1e12693Dc8F9c48aAD8770482f4739bEeD696',
)
multicall2 = _load_contract(
    w3, abi_name='pooler/static/abis/UniswapV3Multicall.json', address=multicall2_addr,
)

# Below two functions derived from: https://stackoverflow.com/questions/71814845/how-to-calculate-uniswap-v3-pools-total-value-locked-tvl-on-chain


def get_token0_in_pool(
    liquidity: float,
    sqrtPrice: float,
    sqrtPriceLow: float,
    sqrtPriceHigh: float,
) -> float:
    sqrtPrice = max(min(sqrtPrice, sqrtPriceHigh), sqrtPriceLow)
    return liquidity * (sqrtPriceHigh - sqrtPrice) / (sqrtPrice * sqrtPriceHigh)


def get_token1_in_pool(
    liquidity: float,
    sqrtPrice: float,
    sqrtPriceLow: float,
    sqrtPriceHigh: float,
) -> float:
    sqrtPrice = max(min(sqrtPrice, sqrtPriceHigh), sqrtPriceLow)
    return liquidity * (sqrtPrice - sqrtPriceLow)


# Find min or max tick in initialized tick range using the tickBitmap
def find_tick_from_bitmap(
    bitmap_spacing: Tuple[int, int],
    pool: Contract,
    tick_spacing: int,
    fee: int,
    left: bool = True,
) -> Union[int, bool]:
    # searching to the left (finding max tick)
    if left:
        min_wordPos = bitmap_spacing[1]
        max_wordPos = bitmap_spacing[0]
        step = -1
    # searching to the right (finding min tick)
    else:
        min_wordPos = bitmap_spacing[0]
        max_wordPos = bitmap_spacing[1]
        step = 1

    # Some fun tickBitmap hacks below.
    # Iterate thru each possible wordPos (based on tick_spacing), get the bitmap "word" (basically a sub-array of the full bitmap),
    # check if there is an initialized tick, derive largest (or smallest) tick in this word
    #
    # Since wordPos (int16 index of tickBitmap mapping) are calculated by (tick/tickspacing) >> 8, deriving tick from wordPos
    # is done by (wordPos << 8)*tickSpacing. This however does not find the precise tick (only a possible tick that could map to that bitmap sub-array, or word),
    # thus we must calculate the nearest viable tick depending on the tick_spacing of the pool using nearest_tick().
    # If searching for the maximum tick, we must then add-back len(bitmap)*tick_spacing as each bit in the bitmap should correspond to a tick.

    for wordPos in range(min_wordPos, max_wordPos, step):
        print('checking', wordPos, 'of', max_wordPos)
        word = pool.functions.tickBitmap(wordPos).call()
        bitmap = bin(word)
        for bit in bitmap[3:]:
            if int(bit) == 1:
                if left:
                    _max_tick = get_max_tick_from_wordpos(
                        wordPos, bitmap, tick_spacing, fee,
                    )
                    return _max_tick
                else:
                    _min_tick = get_min_tick_from_wordpos(
                        wordPos, tick_spacing, fee,
                    )
                    return _min_tick
    return False


def get_tvl_in_pool(pool: Contract) -> Tuple[float, float]:
    """
    Iterate through each tick in a pool and calculate the TVL on-chain

    Note: the output of this function may differ from what is returned by the
    UniswapV3 subgraph api (https://github.com/Uniswap/v3-subgraph/issues/74)

    Params
    ------
    pool: Contract
        pool contract instance to find TVL
    """
    pool_tick_output_types = (
        'uint128',
        'int128',
        'uint256',
        'uint256',
        'int56',
        'uint160',
        'uint32',
        'bool',
    )

    pool_immutables = get_pool_immutables(pool)
    pool_state = get_pool_state(pool)
    fee = pool_immutables['fee']
    sqrtPrice = pool_state['sqrtPriceX96'] / (1 << 96)

    token0_liquidity = 0.0
    token1_liquidity = 0.0
    liquidity_total = 0.0

    TICK_SPACING = _tick_spacing[fee]
    BITMAP_SPACING = _tick_bitmap_range[fee]

    _max_tick = find_tick_from_bitmap(
        BITMAP_SPACING, pool, TICK_SPACING, fee, True,
    )

    print(_max_tick)
    _min_tick = find_tick_from_bitmap(
        BITMAP_SPACING, pool, TICK_SPACING, fee, False,
    )

    print(_min_tick)
    assert _max_tick is not False, 'Error finding max tick'
    assert _min_tick is not False, 'Error finding min tick'

    Batch = namedtuple('Batch', 'ticks batchResults')
    ticks = []
    # Batching pool.functions.tick() calls as these are the major bottleneck to performance
    for batch in list(chunks(range(_min_tick, _max_tick, TICK_SPACING), 100)):
        print(batch)
        _batch = []
        _ticks = []
        for tick in batch:
            _batch.append(
                (
                    pool.address,
                    HexBytes(pool.functions.ticks(tick)._encode_transaction_data()),
                ),
            )
            _ticks.append(tick)
        ticks.append(Batch(_ticks, multicall(_batch, pool_tick_output_types)))

    for tickBatch in ticks:
        print(tickBatch)
        tick_arr = tickBatch.ticks
        for i in range(len(tick_arr)):
            tick = tick_arr[i]
            tickData = tickBatch.batchResults[i]
            # source: https://stackoverflow.com/questions/71814845/how-to-calculate-uniswap-v3-pools-total-value-locked-tvl-on-chain
            liquidityNet = tickData[1]
            liquidity_total += liquidityNet
            sqrtPriceLow = 1.0001 ** (tick // 2)
            sqrtPriceHigh = 1.0001 ** ((tick + TICK_SPACING) // 2)
            token0_liquidity += get_token0_in_pool(
                liquidity_total, sqrtPrice, sqrtPriceLow, sqrtPriceHigh,
            )
            token1_liquidity += get_token1_in_pool(
                liquidity_total, sqrtPrice, sqrtPriceLow, sqrtPriceHigh,
            )

    # Correcting for each token's respective decimals
    token0_decimals = (
        _load_contract_erc20(w3, pool_immutables['token0'])
        .functions.decimals()
        .call()
    )
    token1_decimals = (
        _load_contract_erc20(w3, pool_immutables['token1'])
        .functions.decimals()
        .call()
    )
    token0_liquidity = token0_liquidity // (10**token0_decimals)
    token1_liquidity = token1_liquidity // (10**token1_decimals)
    return (token0_liquidity, token1_liquidity)


pool_instance = _load_contract(
    w3, abi_name='pooler/static/abis/UniswapV3Pool.json', address='0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640',
)

print(pool_instance)

quoter = _load_contract(
    w3, abi_name='pooler/static/abis/Quoter.json', address='0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6',
)


sqrtPriceLimitX96 = 0
price = quoter.functions.quoteExactInputSingle(
    '0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640', '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2', 3000, 1, sqrtPriceLimitX96,
).call()

print(price)
# print(get_tvl_in_pool(pool_instance))
