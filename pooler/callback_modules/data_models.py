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
