from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from pydantic import BaseModel


class EpochBaseSnapshot(BaseModel):
    begin: int
    end: int


class EpochBase(BaseModel):
    epochId: int
    begin: int
    end: int


class EpochBroadcast(EpochBase):
    broadcastId: str


class PowerloomSnapshotEpoch(EpochBroadcast):
    contracts: List[str]


class PowerloomSnapshotProcessMessage(EpochBroadcast):
    contract: str


class PowerloomSnapshotFinalizedMessage(BaseModel):
    epochId: int
    projectId: str
    snapshotCid: str
    broadcastId: str
    timestamp: int


class PowerloomCalculateAggregateMessage(BaseModel):
    messages: List[PowerloomSnapshotFinalizedMessage]
    broadcastId: str
    timestamp: int


class ProcessHubCommand(BaseModel):
    command: str
    pid: Optional[int] = None
    proc_str_id: Optional[str] = None
    init_kwargs: Optional[Dict] = dict()


class SnapshotBase(BaseModel):
    contract: str
    chainHeightRange: EpochBaseSnapshot
    timestamp: float


class AggregateBase(BaseModel):
    epochId: int


class PayloadCommitMessage(BaseModel):
    message: Dict[Any, Any]
    web3Storage: bool
    sourceChainId: int
    projectId: str
    epochId: int


class PayloadCommitFinalizedMessage(BaseModel):
    message: PowerloomSnapshotFinalizedMessage
    web3Storage: bool
    sourceChainId: int
