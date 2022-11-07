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

