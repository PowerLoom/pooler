# PayloadCommit(**{
#         'projectId': project_id,
#         'commitId': payload_commit_id,
#         'payload': payload,
#         #'tentativeBlockHeight': last_tentative_block_height,
#         'web3Storage': web3_storage_flag,
#         'skipAnchorProof': skip_anchor_proof_tx,
#         'sourceChainDetails': source_chain_details
#     })

from pydantic import BaseModel
from typing import Optional, Union


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

class PayloadCommit(BaseModel):
    projectId: str
    commitId: str
    payload: Optional[dict] = None
    # following two can be used to substitute for not supplying the payload but the CID and hash itself
    snapshotCID: Optional[str] = None
    apiKeyHash: Optional[str] = None
    tentativeBlockHeight: int = 0
    resubmitted: bool = False
    resubmissionBlock: int = 0  # corresponds to lastTouchedBlock in PendingTransaction model
    web3Storage: bool = False
    skipAnchorProof: bool = True
    sourceChainDetails: Optional[SourceChainDetails]
