from enum import Enum
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from pydantic import BaseModel

from pooler.utils.models.message_models import AggregateBase


class PayloadCommitAPIRequest(BaseModel):
    projectId: str
    payload: Dict
    web3Storage: bool = False
    # skip anchor tx by default, unless passed
    skipAnchorProof: bool = True
    sourceChainDetails: int


class SnapshotterIssue(BaseModel):
    instanceID: str
    issueType: str
    projectID: str
    epochId: str
    timeOfReporting: str
    extra: Optional[str] = ''


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


class SnapshotSubmittedEvent(EventBase):
    snapshotCid: str
    epochId: int
    projectId: str
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


class WrappedProtocolState(AggregateBase):
    protocol_state_cid: str


class SnapshotterReportState(Enum):
    MISSED_SNAPSHOT = 'MISSED_SNAPSHOT'
    SUBMITTED_INCORRECT_SNAPSHOT = 'SUBMITTED_INCORRECT_SNAPSHOT'


class ProjectStatus(BaseModel):
    projectId: str
    successfulSubmissions: int = 0
    incorrectSubmissions: int = 0
    missedSubmissions: int = 0


class SnapshotterStatus(BaseModel):
    totalSuccessfulSubmissions: int = 0
    totalIncorrectSubmissions: int = 0
    totalMissedSubmissions: int = 0
    projects: List[ProjectStatus]


class SnapshotterMissedSubmission(BaseModel):
    epochId: int
    reason: str


class SnapshotterIncorrectSubmission(BaseModel):
    epochId: int
    incorrectCid: str
    payloadDump: str
    reason: str = ''


class SnapshotterStatusReport(BaseModel):
    submittedSnapshotCid: str
    submittedSnapshot: Dict[str, Any] = {}
    finalizedSnapshotCid: str
    finalizedSnapshot: Dict[str, Any] = {}
    state: SnapshotterReportState
    reason: str = ''


class SnapshotterMissedSnapshotSubmission(BaseModel):
    epochId: int
    finalizedSnapshotCid: str
    reason: str


class SnapshotterIncorrectSnapshotSubmission(BaseModel):
    epochId: int
    submittedSnapshotCid: str
    submittedSnapshot: Optional[Dict[str, Any]]
    finalizedSnapshotCid: str
    finalizedSnapshot: Optional[Dict[str, Any]]
    reason: str = ''


class SnapshotterProjectStatus(BaseModel):
    missedSubmissions: List[SnapshotterMissedSnapshotSubmission]
    incorrectSubmissions: List[SnapshotterIncorrectSnapshotSubmission]
