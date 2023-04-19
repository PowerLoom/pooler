from enum import Enum
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from pydantic import BaseModel


class EpochBase(BaseModel):
    begin: int
    end: int


class EpochBroadcast(EpochBase):
    broadcast_id: str


class EpochConsensusReport(EpochBase):
    reorg: bool = False


class SystemEpochStatusReport(EpochBase):
    broadcast_id: str
    reorg: bool = False


class PowerloomSnapshotEpoch(SystemEpochStatusReport):
    contracts: List[str]


class PowerloomSnapshotProcessMessage(SystemEpochStatusReport):
    contract: str
    coalesced_broadcast_ids: Optional[List[str]] = None
    coalesced_epochs: Optional[List[EpochBase]] = None


class PowerloomSnapshotFinalizedMessage(BaseModel):
    DAGBlockHeight: int
    projectId: str
    snapshotCid: str
    broadcast_id: str
    timestamp: int


class PowerloomIndexFinalizedMessage(BaseModel):
    DAGBlockHeight: int
    projectId: str
    indexTailDAGBlockHeight: int
    tailBlockEpochSourceChainHeight: int
    indexIdentifierHash: str
    broadcast_id: str
    timestamp: int


class PowerloomAggregateFinalizedMessage(BaseModel):
    epochEnd: int
    projectId: str
    aggregateCid: str
    broadcast_id: str
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


class PayloadCommitMessageType(Enum):
    SNAPSHOT = 'SNAPSHOT'
    INDEX = 'INDEX'
    AGGREGATE = 'AGGREGATE'


class PayloadCommitMessage(Enum):
    message_type: PayloadCommitMessageType
    message: Dict[Any, Any]
    web3Storage: bool
    sourceChainId: int


class PayloadCommitFinalizedMessageType(Enum):
    SNAPSHOTFINALIZED = 'SNAPSHOTFINALIZED'
    INDEXFINALIZED = 'INDEXFINALIZED'
    AGGREGATEFINALIZED = 'AGGREGATEFINALIZED'


class PayloadCommitFinalizedMessage(BaseModel):
    message_type: PayloadCommitFinalizedMessageType
    message: Union[
        PowerloomSnapshotFinalizedMessage,
        PowerloomIndexFinalizedMessage,
        PowerloomAggregateFinalizedMessage,
    ]
    web3Storage: bool
    sourceChainId: int
