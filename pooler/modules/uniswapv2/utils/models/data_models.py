from typing import Dict
from typing import List

from pydantic import BaseModel


class TradeData(BaseModel):
    totalTradesUSD: float
    totalFeeUSD: float
    token0TradeVolume: float
    token1TradeVolume: float
    token0TradeVolumeUSD: float
    token1TradeVolumeUSD: float

    def __add__(self, other: 'TradeData') -> 'TradeData':
        self.totalTradesUSD += other.totalTradesUSD
        self.totalFeeUSD += other.totalFeeUSD
        self.token0TradeVolume += other.token0TradeVolume
        self.token1TradeVolume += other.token1TradeVolume
        self.token0TradeVolumeUSD += other.token0TradeVolumeUSD
        self.token1TradeVolumeUSD += other.token1TradeVolumeUSD
        return self

    def __sub__(self, other: 'TradeData') -> 'TradeData':
        self.totalTradesUSD -= other.totalTradesUSD
        self.totalFeeUSD -= other.totalFeeUSD
        self.token0TradeVolume -= other.token0TradeVolume
        self.token1TradeVolume -= other.token1TradeVolume
        self.token0TradeVolumeUSD -= other.token0TradeVolumeUSD
        self.token1TradeVolumeUSD -= other.token1TradeVolumeUSD
        return self

    def __abs__(self) -> 'TradeData':
        self.totalTradesUSD = abs(self.totalTradesUSD)
        self.totalFeeUSD = abs(self.totalFeeUSD)
        self.token0TradeVolume = abs(self.token0TradeVolume)
        self.token1TradeVolume = abs(self.token1TradeVolume)
        self.token0TradeVolumeUSD = abs(self.token0TradeVolumeUSD)
        self.token1TradeVolumeUSD = abs(self.token1TradeVolumeUSD)
        return self


class TradeEventLogs(BaseModel):
    Swap: List[Dict]
    Mint: List[Dict]
    Burn: List[Dict]
