from pydantic import BaseModel
from typing import Optional


class RedisConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None


class ServerListenerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int


class AuthSettings(BaseModel):
    redis: RedisConfig
    bind: ServerListenerConfig