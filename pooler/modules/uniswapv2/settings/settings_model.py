from typing import List

from pydantic import BaseModel
from pydantic import Field


class UniswapContractAbis(BaseModel):
    factory: str = Field(
        ..., example='pooler/modules/uniswapv2static/abis/IUniswapV2Factory.json',
    )
    router: str = Field(..., example='pooler/modules/uniswapv2/static/abis/UniswapV2Router.json')
    pair_contract: str = Field(
        ..., example='pooler/modules/uniswapv2/static/abis/UniswapV2Pair.json',
    )
    erc20: str = Field(..., example='pooler/modules/uniswapv2/static/abis/IERC20.json')
    trade_events: str = Field(
        ..., example='pooler/modules/uniswapv2/static/abis/UniswapTradeEvents.json',
    )


class ContractAddresses(BaseModel):
    iuniswap_v2_factory: str = Field(
        ..., example='0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32',
    )
    iuniswap_v2_router: str = Field(
        ..., example='0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff',
    )
    MAKER: str = Field(
        ..., example='0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2',
    )
    USDT: str = Field(..., example='0xc2132d05d31c914a87c6611c10748aeb04b58e8f')
    DAI: str = Field(..., example='0x8f3cf7ad23cd3cadbd9735aff958023239c6a063')
    USDC: str = Field(..., example='0x2791bca1f2de4661ed88a30c99a7a9449aa84174')
    WETH: str = Field(..., example='0x7ceb23fd6bc0add59e62ac25578270cff1b9f619')
    WETH_USDT: str = Field(
        ..., example='0xf6422b997c7f54d1c6a6e103bcb1499eea0a7046',
    )
    FRAX: str = Field(..., example='0x853d955aCEf822Db058eb8505911ED77F175b99e')
    SYN: str = Field(..., example='0x0f2D719407FdBeFF09D87557AbB7232601FD9F29')
    FEI: str = Field(..., example='0x956F47F50A910163D8BF957Cf5846D573E7f87CA')
    agEUR: str = Field(
        ..., example='0x1a7e4e63778B4f12a199C062f3eFdD288afCBce8',
    )
    DAI_WETH_PAIR: str = Field(
        ..., example='0xa478c2975ab1ea89e8196811f51a7b7ade33eb11',
    )
    USDC_WETH_PAIR: str = Field(
        ..., example='0xb4e16d0168e52d35cacd2c6185b44281ec28c9',
    )
    USDT_WETH_PAIR: str = Field(
        ..., example='0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852',
    )


class Settings(BaseModel):
    uniswap_contract_abis: UniswapContractAbis
    contract_addresses: ContractAddresses
    uniswap_v2_whitelist: List[str]
