import asyncio
from enum import Enum
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from pydantic import BaseModel

from snapshotter.utils.callback_helpers import GenericPreloader


class ProcessorWorkerDetails(BaseModel):
    unique_name: str
    pid: Union[None, int] = None


class PreloaderAsyncFutureDetails(BaseModel):
    obj: GenericPreloader
    future: asyncio.Task

    class Config:
        arbitrary_types_allowed = True


class SnapshotterReportState(Enum):
    MISSED_SNAPSHOT = 'MISSED_SNAPSHOT'
    SUBMITTED_INCORRECT_SNAPSHOT = 'SUBMITTED_INCORRECT_SNAPSHOT'
    SHUTDOWN_INITIATED = 'SHUTDOWN_INITIATED'
    CRASHED_CHILD_WORKER = 'CRASHED_CHILD_WORKER'
    CRASHED_REPORTER_THREAD = 'CRASHED_REPORTER_THREAD'
    UNHEALTHY_EPOCH_PROCESSING = 'UNHEALTHY_EPOCH_PROCESSING'


class SnapshotterStates(Enum):
    PRELOAD = 'PRELOAD'
    SNAPSHOT_BUILD = 'SNAPSHOT_BUILD'
    SNAPSHOT_SUBMIT_PAYLOAD_COMMIT = 'SNAPSHOT_SUBMIT_PAYLOAD_COMMIT'
    RELAYER_SEND = 'RELAYER_SEND'
    SNAPSHOT_FINALIZE = 'SNAPSHOT_FINALIZE'


class SnapshotterStateUpdate(BaseModel):
    status: str
    error: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    timestamp: int


class SnapshotterEpochProcessingReportItem(BaseModel):
    epochId: int = 0
    epochEnd: int = 0
    # map transition like EPOCH_RELEASED to its status
    transitionStatus: Dict[str, Union[SnapshotterStateUpdate, None, Dict[str, SnapshotterStateUpdate]]] = dict()


class SnapshotterIssue(BaseModel):
    instanceID: str
    issueType: str
    projectID: str
    epochId: str
    timeOfReporting: str
    extra: Optional[str] = ''


class DelegateTaskProcessorIssue(BaseModel):
    instanceID: str
    issueType: str
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


class SnapshotFinalizedEvent(EventBase):
    epochId: int
    epochEnd: int
    projectId: str
    snapshotCid: str


class ProjectsUpdatedEvent(EventBase):
    projectId: str
    allowed: bool
    enableEpochId: int


class SnapshottersUpdatedEvent(EventBase):
    snapshotterAddress: str
    allowed: bool


class SnapshotSubmittedEvent(EventBase):
    snapshotCid: str
    epochId: int
    projectId: str


class ProjectSpecificState(BaseModel):
    first_epoch_id: int
    finalized_cids: Dict[int, str]  # mapping of epoch ID to snapshot CID


class ProtocolState(BaseModel):
    project_specific_states: Dict[str, ProjectSpecificState]  # project ID -> project specific state
    synced_till_epoch_id: int


class ProjectStatus(BaseModel):
    projectId: str
    successfulSubmissions: int = 0
    incorrectSubmissions: int = 0
    missedSubmissions: int = 0


class SnapshotterPing(BaseModel):
    instanceID: str


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


class UnfinalizedSnapshot(BaseModel):
    snapshotCid: str
    snapshot: Dict[str, Any]


class TaskStatusRequest(BaseModel):
    task_type: str
    wallet_address: str
