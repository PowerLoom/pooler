from typing import Dict
from typing import List

from pydantic import BaseModel

from snapshotter.utils.models.message_models import AggregateBase


class EpochBaseSnapshot(BaseModel):
    begin: int
    end: int


class SnapshotBase(BaseModel):
    contract: str
    chainHeightRange: EpochBaseSnapshot
    timestamp: float


class UniswapPairTotalReservesSnapshot(SnapshotBase):
    token0Reserves: Dict[
        str,
        float,
    ]  # block number to corresponding total reserves
    token1Reserves: Dict[
        str,
        float,
    ]  # block number to corresponding total reserves
    token0ReservesUSD: Dict[str, float]
    token1ReservesUSD: Dict[str, float]
    token0Prices: Dict[str, float]
    token1Prices: Dict[str, float]


class logsTradeModel(BaseModel):
    logs: List
    trades: Dict[str, float]


class UniswapTradeEvents(BaseModel):
    Swap: logsTradeModel
    Mint: logsTradeModel
    Burn: logsTradeModel
    Trades: Dict[str, float]


class UniswapTradesSnapshot(SnapshotBase):
    totalTrade: float  # in USD
    totalFee: float  # in USD
    token0TradeVolume: float  # in token native decimals supply
    token1TradeVolume: float  # in token native decimals supply
    token0TradeVolumeUSD: float
    token1TradeVolumeUSD: float
    events: UniswapTradeEvents


class UniswapTradesAggregateSnapshot(AggregateBase):
    totalTrade: float = 0  # in USD
    totalFee: float = 0  # in USD
    token0TradeVolume: float = 0  # in token native decimals supply
    token1TradeVolume: float = 0  # in token native decimals supply
    token0TradeVolumeUSD: float = 0
    token1TradeVolumeUSD: float = 0
    complete: bool = True


class UniswapTopTokenSnapshot(BaseModel):
    name: str
    symbol: str
    decimals: int
    address: str
    price: float
    priceChange24h: float
    volume24h: float
    liquidity: float


class UniswapTopTokensSnapshot(AggregateBase):
    tokens: List[UniswapTopTokenSnapshot] = []
    complete: bool = True


class UniswapTopPair24hSnapshot(BaseModel):
    name: str
    address: str
    liquidity: float
    volume24h: float
    fee24h: float


class UniswapTopPairs24hSnapshot(AggregateBase):
    pairs: List[UniswapTopPair24hSnapshot] = []
    complete: bool = True


class UniswapTopPair7dSnapshot(BaseModel):
    name: str
    address: str
    volume7d: float
    fee7d: float


class UniswapTopPairs7dSnapshot(AggregateBase):
    pairs: List[UniswapTopPair7dSnapshot] = []
    complete: bool = True


class UniswapStatsSnapshot(AggregateBase):
    volume24h: float = 0
    tvl: float = 0
    fee24h: float = 0
    volumeChange24h: float = 0
    tvlChange24h: float = 0
    feeChange24h: float = 0
    complete: bool = True
