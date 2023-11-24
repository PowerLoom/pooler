import uuid
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


class PowerloomSnapshotProcessMessage(EpochBase):
    data_source: Optional[str] = None
    primary_data_source: Optional[str] = None
    genesis: Optional[bool] = False
    bulk_mode: Optional[bool] = False


class PowerloomSnapshotFinalizedMessage(BaseModel):
    epochId: int
    projectId: str
    snapshotCid: str
    timestamp: int


class PowerloomProjectsUpdatedMessage(BaseModel):
    projectId: str
    allowed: bool
    enableEpochId: int


class PowerloomSnapshotSubmittedMessage(BaseModel):
    snapshotCid: str
    epochId: int
    projectId: str
    timestamp: int


class PowerloomDelegateWorkerRequestMessage(BaseModel):
    epochId: int
    requestId: int
    task_type: str
    extra: Optional[Dict[Any, Any]] = dict()


class PowerloomDelegateWorkerResponseMessage(BaseModel):
    epochId: int
    requestId: int


class PowerloomDelegateTxReceiptWorkerResponseMessage(PowerloomDelegateWorkerResponseMessage):
    txHash: str
    txReceipt: Dict[Any, Any]


class PowerloomCalculateAggregateMessage(BaseModel):
    messages: List[PowerloomSnapshotSubmittedMessage]
    epochId: int
    timestamp: int


class ProcessHubCommand(BaseModel):
    command: str
    pid: Optional[int] = None
    proc_str_id: Optional[str] = None
    init_kwargs: Optional[Dict] = dict()


class AggregateBase(BaseModel):
    epochId: int


class PayloadCommitMessage(BaseModel):
    sourceChainId: int
    projectId: str
    epochId: int
    snapshotCID: str


class PayloadCommitFinalizedMessage(BaseModel):
    message: PowerloomSnapshotFinalizedMessage
    web3Storage: bool
    sourceChainId: int
