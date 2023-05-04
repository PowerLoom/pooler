from typing import Dict
from typing import List

from pydantic import BaseModel

from pooler.utils.models.message_models import AggregateBase
from pooler.utils.models.message_models import SnapshotBase


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


class UniswapTopTokenSnapshot(BaseModel):
    name: str
    symbol: str
    decimals: int
    address: str
    price: float
    price_change: float
    volume_24h: float
    liquidity: float


class UniswapTopTokensSnapshot(AggregateBase):
    tokens: List[UniswapTopTokenSnapshot] = []
