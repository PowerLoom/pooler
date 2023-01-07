from enum import Enum
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
