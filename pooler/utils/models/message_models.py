from enum import Enum
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from pydantic import BaseModel


class EpochBase(BaseModel):
    begin: int
    end: int


class EpochBroadcast(EpochBase):
    broadcastId: str


class EpochConsensusReport(EpochBase):
    reorg: bool = False


class SystemEpochStatusReport(EpochBase):
    broadcastId: str
    reorg: bool = False


class PowerloomSnapshotEpoch(SystemEpochStatusReport):
    contracts: List[str]


class PowerloomSnapshotProcessMessage(SystemEpochStatusReport):
    contract: str


class PowerloomSnapshotFinalizedMessage(BaseModel):
    DAGBlockHeight: int
    projectId: str
    snapshotCid: str
    broadcastId: str
    timestamp: int


class PowerloomIndexFinalizedMessage(BaseModel):
    DAGBlockHeight: int
    projectId: str
    indexTailDAGBlockHeight: int
    tailBlockEpochSourceChainHeight: int
    indexIdentifierHash: str
    broadcastId: str
    timestamp: int


class PowerloomAggregateFinalizedMessage(BaseModel):
    DAGBlockHeight: int
    projectId: str
    aggregateCid: str
    broadcastId: str
    timestamp: int


class PowerloomCalculateAggregateMessage(BaseModel):
    messages: List[PowerloomAggregateFinalizedMessage]
    broadcastId: str
    timestamp: int


class ProcessHubCommand(BaseModel):
    command: str
    pid: Optional[int] = None
    proc_str_id: Optional[str] = None
    init_kwargs: Optional[Dict] = dict()


class SnapshotBase(BaseModel):
    contract: str
    chainHeightRange: EpochBase
    timestamp: float


class IndexBase(BaseModel):
    DAGBlockHeight: int


class AggregateBase(BaseModel):
    DAGBlockHeight: int


class PayloadCommitMessageType(Enum):
    SNAPSHOT = 'SNAPSHOT'
    INDEX = 'INDEX'
    AGGREGATE = 'AGGREGATE'


class PayloadCommitMessage(BaseModel):
    messageType: PayloadCommitMessageType
    message: Dict[Any, Any]
    web3Storage: bool
    sourceChainId: int
    projectId: str
    epochEndHeight: int


class PayloadCommitFinalizedMessageType(Enum):
    SNAPSHOTFINALIZED = 'SNAPSHOTFINALIZED'
    INDEXFINALIZED = 'INDEXFINALIZED'
    AGGREGATEFINALIZED = 'AGGREGATEFINALIZED'


class PayloadCommitFinalizedMessage(BaseModel):
    messageType: PayloadCommitFinalizedMessageType
    message: Union[
        PowerloomSnapshotFinalizedMessage,
        PowerloomIndexFinalizedMessage,
        PowerloomAggregateFinalizedMessage,
    ]
    web3Storage: bool
    sourceChainId: int
