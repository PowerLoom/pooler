from typing import List, Optional

from pydantic import BaseModel

from snapshotter.utils.models.settings_model import RPCConfigBase

class RedisConfig(BaseModel):
    host: str = '127.0.0.1'
    port: int = 6379
    db: int = 0
    password: Optional[str] = None


class ServerListenerConfig(BaseModel):
    host: str = '0.0.0.0'
    port: int

class Signer(BaseModel):
    address: str
    private_key: str


class AuthSettings(BaseModel):
    redis: RedisConfig
    bind: ServerListenerConfig
    signers: List[Signer]
    min_signer_balance_eth: int
    protocol_state_contracts: List[str]
