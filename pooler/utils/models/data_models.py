from enum import Enum
from typing import Dict
from typing import List
from typing import Optional

from pydantic import BaseModel


class SourceChainDetails(BaseModel):
    chainID: int
    epochStartHeight: int
    epochEndHeight: int


class PayloadCommitAPIRequest(BaseModel):
    projectId: str
    payload: dict
    web3Storage: bool = False
    # skip anchor tx by default, unless passed
    skipAnchorProof: bool = True
    sourceChainDetails: SourceChainDetails


class SnapshotterIssueSeverity(str, Enum):
    high = 'HIGH'
    medium = 'MEDIUM'
    low = 'LOW'
    cleared = 'CLEARED'


class SnapshotterIssueType(str, Enum):
    snapshotting_fallen_behind = 'SNAPSHOTTING_FALLEN_BEHIND'
    missed_snapshot = 'MISSED_SNAPSHOT'
    infra_issue = 'INFRA_ISSUE'
    skip_epoch = 'SKIP_EPOCH'
    dag_chain_stuck = 'DAG_CHAIN_STUCK'
    pruning_failed = 'PRUNING_FAILED'


class SnapshotterIssue(BaseModel):
    instanceID: str
    namespace: Optional[str]
    severity: SnapshotterIssueSeverity
    issueType: str
    projectID: str
    epochs: Optional[List[int]]
    timeOfReporting: int
    noOfEpochsBehind: Optional[int]
    extra: Optional[dict]
    serviceName: str


class TimeoutConfig(BaseModel):
    basic: int
    archival: int
    connection_init: int


class RLimitConfig(BaseModel):
    file_descriptors: int


class liquidityProcessedData(BaseModel):
    contractAddress: str
    name: str
    liquidity: str
    volume_24h: str
    volume_7d: str
    cid_volume_24h: str
    cid_volume_7d: str
    fees_24h: str
    block_height: int
    deltaToken0Reserves: float
    deltaToken1Reserves: float
    deltaTime: float
    latestTimestamp: float
    earliestTimestamp: float


class trade_data(BaseModel):
    totalTradesUSD: float
    totalFeeUSD: float
    token0TradeVolume: float
    token1TradeVolume: float
    token0TradeVolumeUSD: float
    token1TradeVolumeUSD: float

    def __add__(self, other: 'trade_data') -> 'trade_data':
        self.totalTradesUSD += other.totalTradesUSD
        self.totalFeeUSD += other.totalFeeUSD
        self.token0TradeVolume += other.token0TradeVolume
        self.token1TradeVolume += other.token1TradeVolume
        self.token0TradeVolumeUSD += other.token0TradeVolumeUSD
        self.token1TradeVolumeUSD += other.token1TradeVolumeUSD
        return self

    def __sub__(self, other: 'trade_data') -> 'trade_data':
        self.totalTradesUSD -= other.totalTradesUSD
        self.totalFeeUSD -= other.totalFeeUSD
        self.token0TradeVolume -= other.token0TradeVolume
        self.token1TradeVolume -= other.token1TradeVolume
        self.token0TradeVolumeUSD -= other.token0TradeVolumeUSD
        self.token1TradeVolumeUSD -= other.token1TradeVolumeUSD
        return self

    def __abs__(self) -> 'trade_data':
        self.totalTradesUSD = abs(self.totalTradesUSD)
        self.totalFeeUSD = abs(self.totalFeeUSD)
        self.token0TradeVolume = abs(self.token0TradeVolume)
        self.token1TradeVolume = abs(self.token1TradeVolume)
        self.token0TradeVolumeUSD = abs(self.token0TradeVolumeUSD)
        self.token1TradeVolumeUSD = abs(self.token1TradeVolumeUSD)
        return self


class event_trade_data(BaseModel):
    logs: List[dict]
    trades: trade_data


class epoch_event_trade_data(BaseModel):
    Swap: event_trade_data
    Mint: event_trade_data
    Burn: event_trade_data
    Trades: trade_data


class EpochInfo(BaseModel):
    chainId: int
    epochStartBlockHeight: int
    epochEndBlockHeight: int


class ProjectRegistrationRequest(BaseModel):
    projectIDs: List[str]


class IndexingRegistrationData(BaseModel):
    projectID: str
    indexerConfig: Dict


class ProjectRegistrationRequestForIndexing(BaseModel):
    projects: List[IndexingRegistrationData]
    namespace: str
