from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class TxLogsModel(BaseModel):
    logIndex: str
    blockNumber: str
    blockHash: str
    transactionHash: str
    transactionIndex: str
    address: str
    data: str
    topics: List[str]


class EthTransactionReceipt(BaseModel):
    transactionHash: str
    transactionIndex: str
    blockHash: str
    blockNumber: str
    from_field: str = Field(..., alias='from')
    to: Optional[str]
    cumulativeGasUsed: str
    gasUsed: str
    effectiveGasPrice: str
    logs: List[TxLogsModel]
    contractAddress: Optional[str] = None
    logsBloom: str
    status: str
    type: Optional[str]
    root: Optional[str]


class EpochBase(BaseModel):
    epochId: int
    begin: int
    end: int


class SlotsPerDayUpdatedMessage(BaseModel):
    slotsPerDay: int


class SnapshotProcessMessage(EpochBase):
    genesis: Optional[bool] = False


class SnapshotFinalizedMessage(BaseModel):
    epochId: int
    projectId: str
    snapshotCid: str
    timestamp: int


class SnapshotSubmittedMessage(BaseModel):
    snapshotCid: str
    epochId: int
    projectId: str
    timestamp: int


class SnapshotSubmittedMessageLite(BaseModel):
    snapshotCid: str
    projectId: str


class ProjectTypeProcessingCompleteMessage(BaseModel):
    epochId: int
    projectType: str
    snapshotsSubmitted: List[SnapshotSubmittedMessageLite]


class DelegateWorkerRequestMessage(BaseModel):
    epochId: int
    requestId: int
    task_type: str
    extra: Optional[Dict[Any, Any]] = dict()


class DelegateWorkerResponseMessage(BaseModel):
    epochId: int
    requestId: int


class DelegateTxReceiptWorkerResponseMessage(DelegateWorkerResponseMessage):
    txHash: str
    txReceipt: Dict[Any, Any]


class CalculateAggregateMessage(BaseModel):
    messages: List[ProjectTypeProcessingCompleteMessage]
    epochId: int
    timestamp: int


class ProcessHubCommand(BaseModel):
    command: str
    pid: Optional[int] = None
    proc_str_id: Optional[str] = None
    init_kwargs: Optional[Dict] = dict()


class AggregateBase(BaseModel):
    epochId: int
