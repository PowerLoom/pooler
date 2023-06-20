from pydantic import BaseModel
from pydantic import Field


class UniswapContractAbis(BaseModel):
    factory: str = Field(
        ..., example='pooler/modules/uniswapv3/static/abis/IUniswapV3Factory.json',
    )
    router: str = Field(
        ..., example='pooler/modules/uniswapv3/static/abis/UniswapV3Router.json',
    )
    quoter: str = Field(
        ..., example='pooler/modules/uniswapv3/static/abis/Quoter.json',
    )
    multicall: str = Field(
        ..., example='pooler/modules/uniswapv3/static/abis/UniswapV3Multicall.json',
    )
    pair_contract: str = Field(
        ..., example='pooler/modules/uniswapv3/static/abis/UniswapV3Pool.json',
    )
    erc20: str = Field(
        ..., example='pooler/modules/uniswapv3/static/abis/IERC20.json',
    )
    trade_events: str = Field(
        ..., example='pooler/modules/uniswapv3/static/abis/UniswapTradeEvents.json',
    )


class ContractAddresses(BaseModel):
    uniswap_v3_factory: str = Field(
        ..., example='0x1F98431c8aD98523631AE4a59f267346ea31F984',
    )
    uniswap_v3_router: str = Field(
        ..., example='0xE592427A0AEce92De3Edee1F18E0157C05861564',
    )
    uniswap_v3_quoter: str = Field(
        ..., example='0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6',
    )
    uniswap_v3_multicall: str = Field(
        ..., example='0x5BA1e12693Dc8F9c48aAD8770482f4739bEeD696',
    )


class Settings(BaseModel):
    uniswap_contract_abis: UniswapContractAbis
    contract_addresses: ContractAddresses
