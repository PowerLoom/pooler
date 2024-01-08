from typing import List
from typing import Optional

from ipfs_client.settings.data_models import IPFSConfig
from pydantic import BaseModel


class CoreAPI(BaseModel):
    host: str
    port: int


class RPCNodeConfig(BaseModel):
    url: str


class ConnectionLimits(BaseModel):
    max_connections: int = 100
    max_keepalive_connections: int = 50
    keepalive_expiry: int = 300


class RPCConfigBase(BaseModel):
    full_nodes: List[RPCNodeConfig]
    archive_nodes: Optional[List[RPCNodeConfig]]
    force_archive_blocks: Optional[int]
    retry: int
    request_time_out: int
    connection_limits: ConnectionLimits


class RPCConfigFull(RPCConfigBase):
    skip_epoch_threshold_blocks: int
    polling_interval: int


class RLimit(BaseModel):
    file_descriptors: int


class Timeouts(BaseModel):
    basic: int
    archival: int
    connection_init: int


class ReportingConfig(BaseModel):
    slack_url: str
    service_url: str


class Logs(BaseModel):
    trace_enabled: bool
    write_to_files: bool


class EventContract(BaseModel):
    address: str
    abi: str
    deadline_buffer: int


class IPFSWriterRateLimit(BaseModel):
    req_per_sec: int
    burst: int


class ExternalAPIAuth(BaseModel):
    # this is most likely used as a basic auth tuple of (username, password)
    apiKey: str
    apiSecret: str = ''


class Web3Storage(BaseModel):
    upload_snapshots: bool
    url: str
    upload_url_suffix: str
    api_token: str
    timeout: int
    max_idle_conns: int
    idle_conn_timeout: int


class Relayer(BaseModel):
    host: str
    endpoint: str


class Settings(BaseModel):
    namespace: str
    core_api: CoreAPI
    instance_id: str
    signer_private_key: str
    rpc: RPCConfigFull
    rlimit: RLimit
    reporting: ReportingConfig
    logs: Logs
    projects_config_path: str
    pair_contract_abi: str
    protocol_state: EventContract
    relayer: Relayer
    ipfs: IPFSConfig
    web3storage: Web3Storage
    anchor_chain_rpc: RPCConfigBase


# Projects related models
class ProcessorConfig(BaseModel):
    module: str
    class_name: str


class ProjectConfig(BaseModel):
    project_type: str
    processor: ProcessorConfig


class ProjectsConfig(BaseModel):
    config: List[ProjectConfig]
