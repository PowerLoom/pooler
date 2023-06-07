from typing import Dict
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


class ProtocolState(AggregateBase):
    project_specific_states: Dict[str, ProjectSpecificState]  # project ID -> project specific state
    synced_till_epoch_id: int
