from enum import Enum
from typing import Dict
from typing import List
from typing import Optional

from pydantic import BaseModel


class PayloadCommitAPIRequest(BaseModel):
    projectId: str
    payload: Dict
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
    extra: Optional[Dict]
    serviceName: str


class TimeoutConfig(BaseModel):
    basic: int
    archival: int
    connection_init: int


class RLimitConfig(BaseModel):
    file_descriptors: int


# Event detector related models
class EventBase(BaseModel):
    timestamp: int


class EpochReleasedEvent(EventBase):
    epochId: int
    begin: int
    end: int
    broadcastId: str


class SnapshotFinalizedEvent(EventBase):
    epochId: int
    epochEnd: int
    projectId: str
    snapshotCid: str
    broadcastId: str


class PairTradeVolume(BaseModel):
    total_volume: int = 0
    fees: int = 0
    token0_volume: int = 0
    token1_volume: int = 0
    token0_volume_usd: int = 0
    token1_volume_usd: int = 0


class ProjectSpecificState(BaseModel):
    first_epoch_id: int
    finalized_cids: Dict[int, str]  # mapping of epoch ID to snapshot CID


class ProtocolState(BaseModel):
    project_specific_states: Dict[str, ProjectSpecificState]  # project ID -> project specific state
    synced_till_epoch_id: int