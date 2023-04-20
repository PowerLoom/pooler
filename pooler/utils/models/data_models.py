from enum import Enum
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from pydantic import BaseModel


class PayloadCommitAPIRequest(BaseModel):
    projectId: str
    payload: dict
    web3Storage: bool = False
    # skip anchor tx by default, unless passed
    skipAnchorProof: bool = True
    sourceChainDetails: int


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


# Event detector related models
class EventBase(BaseModel):
    timestamp: int


class EpochReleasedEvent(EventBase):
    begin: int
    end: int
    broadcastId: str


class SnapshotFinalizedEvent(EventBase):
    DAGBlockHeight: int
    projectId: str
    snapshotCid: str
    broadcastId: str


class IndexFinalizedEvent(EventBase):
    projectId: str
    DAGBlockHeight: int
    indexTailDAGBlockHeight: int
    tailBlockEpochSourceChainHeight: int
    indexIdentifierHash: str
    broadcastId: str


class AggregateFinalizedEvent(EventBase):
    epochEnd: int
    projectId: str
    aggregateCid: str
    broadcastId: str


# Indexing and Aggregation related models
class BlockRetrievalFlags(int, Enum):
    only_dag_block = 0
    dag_block_and_payload_data = 1
    only_payload_data = 2


class DAGBlockPayloadLinkedPath(BaseModel):
    cid: Dict[str, str]


# DAGBlockPayloadLinkedPath is transformed by retrieval utilities
# for an easy to access RetrievedDAGBlockPayload object
class RetrievedDAGBlockPayload(BaseModel):
    cid: str = 'null'
    payload: Union[dict, None] = None


class RetrievedDAGBlock(BaseModel):
    height: int = 0
    prevCid: Optional[Dict[str, str]] = None
    prevRoot: Optional[str] = None
    data: RetrievedDAGBlockPayload = RetrievedDAGBlockPayload()
    txHash: str = ''
    timestamp: int = 0


class IndexSeek(BaseModel):
    dagBlockHead: Optional[RetrievedDAGBlock] = None
    dagBlockTail: Optional[RetrievedDAGBlock] = None
    dagBlockTailCid: Optional[str] = None
    # block number in epoch range contained by DAGBlock at
    # dagBlockCidTail: dagBlock.data.payload['chainHeightRange']
    # soureChainBlockNum in the range ∈ (epoch_range['begin'], epoch_range['end']]
    sourceChainBlockNum: int = 0


class CachedDAGTailMarker(BaseModel):
    height: int
    cid: str
    sourceChainBlockNum: int


class CachedIndexMarker(BaseModel):
    dagTail: CachedDAGTailMarker
    dagHeadCid: str


class TailAdjustmentCursor(BaseModel):
    dag_block_height: int
    dag_block: RetrievedDAGBlock
    dag_block_cid: str
    epoch_range: tuple


class IndexFinalizedCallback(BaseModel):
    projectId: str
    DAGBlockHeight: int
    indexTailDAGBlockHeight: int
    tailBlockEpochSourceChainHeight: int
    indexIdentifierHash: str
    timestamp: int


class CachedAggregateMarker(BaseModel):
    dagTail: CachedDAGTailMarker
    dagHeadCid: str
    aggregate: dict


class PairTradeVolume(BaseModel):
    total_volume: int = 0
    fees: int = 0
    token0_volume: int = 0
    token1_volume: int = 0
    token0_volume_usd: int = 0
    token1_volume_usd: int = 0
