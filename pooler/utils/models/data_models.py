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


class EventBase(BaseModel):
    timestamp: int


class EpochReleasedEvent(EventBase):
    begin: int
    end: int
    broadcast_id: str


class EpochFinalizedEvent(EventBase):
    DAGBlockHeight: int
    projectId: str
    snapshotCid: str


class IndexFinalizedEvent(EventBase):
    projectId: str
    DAGBlockHeight: int
    indexTailDAGBlockHeight: int
    tailBlockEpochSourceChainHeight: int
    indexIdentifierHash: str
