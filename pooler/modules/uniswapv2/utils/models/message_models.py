from typing import List

from pydantic import BaseModel

from .data_models import TradeEventLogs
from pooler.utils.models.message_models import AggregateBase
from pooler.utils.models.message_models import SnapshotBase


class UniswapPairTotalReservesSnapshot(SnapshotBase):
    token0Reserves: List[float]
    token1Reserves: List[float]
    token0ReservesUSD: List[float]
    token1ReservesUSD: List[float]
    token0Prices: List[float]
    token1Prices: List[float]


class UniswapTradesSnapshot(SnapshotBase):
    totalTradesUSD: List[float]  # in USD
    totalFeesUSD: List[float]  # in USD
    token0TradeVolumes: List[float]  # in token native decimals supply
    token1TradeVolumes: List[float]  # in token native decimals supply
    token0TradeVolumesUSD: List[float]
    token1TradeVolumesUSD: List[float]
    events: List[TradeEventLogs]


class UniswapTradesAggregateSnapshot(AggregateBase):
    totalTrade: float = 0  # in USD
    totalFee: float = 0  # in USD
    token0TradeVolume: float = 0  # in token native decimals supply
    token1TradeVolume: float = 0  # in token native decimals supply
    token0TradeVolumeUSD: float = 0
    token1TradeVolumeUSD: float = 0


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


class UniswapTopPair24hSnapshot(BaseModel):
    name: str
    address: str
    liquidity: float
    volume24h: float
    fee24h: float


class UniswapTopPairs24hSnapshot(AggregateBase):
    pairs: List[UniswapTopPair24hSnapshot] = []


class UniswapTopPair7dSnapshot(BaseModel):
    name: str
    address: str
    volume7d: float
    fee7d: float


class UniswapTopPairs7dSnapshot(AggregateBase):
    pairs: List[UniswapTopPair7dSnapshot] = []


class UniswapStatsSnapshot(AggregateBase):
    volume24h: float = 0
    tvl: float = 0
    fee24h: float = 0
    volumeChange24h: float = 0
    tvlChange24h: float = 0
    feeChange24h: float = 0
