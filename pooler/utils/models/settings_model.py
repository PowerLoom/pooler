from typing import List
from typing import Optional
from typing import Union

from pydantic import BaseModel
from pydantic import Field


class Auth(BaseModel):
    enabled: bool = Field(True, description='Whether auth is enabled or not')
    header_key: str = Field('X-API-KEY', description='Key used for auth')


class CoreAPI(BaseModel):
    host: str
    port: int
    auth: Auth
    public_rate_limit: str


class RPCNodeConfig(BaseModel):
    url: str
    rate_limit: str


class RPCConfigBase(BaseModel):
    full_nodes: List[RPCNodeConfig]
    archive_nodes: Optional[List[RPCNodeConfig]]
    force_archive_blocks: Optional[int]
    retry: int
    request_time_out: int


class RPCConfigFull(RPCConfigBase):
    skip_epoch_threshold_blocks: int
    polling_interval: int


class RLimit(BaseModel):
    file_descriptors: int


class Timeouts(BaseModel):
    basic: int
    archival: int
    connection_init: int


class QueueConfig(BaseModel):
    num_instances: int


class Epoch(BaseModel):
    height: int
    head_offset: int
    block_time: int


class RabbitMQConfig(BaseModel):
    exchange: str


class RabbitMQSetup(BaseModel):
    core: RabbitMQConfig
    callbacks: RabbitMQConfig
    event_detector: RabbitMQConfig


class RabbitMQ(BaseModel):
    user: str
    password: str
    host: str
    port: int
    setup: RabbitMQSetup


class AuditProtocolEngine(BaseModel):
    url: str
    retry: int
    skip_anchor_proof: bool


class Consensus(BaseModel):
    url: str
    epoch_tracker_path: str
    polling_interval: int
    fall_behind_reset_num_blocks: int
    sleep_secs_between_chunks: int


class Redis(BaseModel):
    host: str
    port: int
    db: int
    password: Union[str, None] = None
    ssl: bool = False
    cluster_mode: bool = False


class RedisReader(BaseModel):
    host: str
    port: int
    db: int
    password: Union[str, None] = None
    ssl: bool = False
    cluster_mode: bool = False


class WebhookListener(BaseModel):
    host: str
    port: int


class Logs(BaseModel):
    trace_enabled: bool
    write_to_files: bool


class EventContract(BaseModel):
    address: str
    abi: str


class CallbackWorkerConfig(BaseModel):
    num_snapshot_workers: int
    num_indexing_workers: int
    num_aggregation_workers: int


class IPFSWriterRateLimit(BaseModel):
    req_per_sec: int
    burst: int


class IPFSconfig(BaseModel):
    url: str
    reader_url: str
    write_rate_limit: IPFSWriterRateLimit
    timeout: int
    local_cache_path: str


class Settings(BaseModel):
    namespace: str
    core_api: CoreAPI
    chain_id: int
    instance_id: str
    ipfs_url: str
    logs_prune_time: int
    rpc: RPCConfigFull
    issue_report_url: str
    rlimit: RLimit
    timeouts: Timeouts
    epoch: Epoch
    rabbitmq: RabbitMQ
    audit_protocol_engine: AuditProtocolEngine
    consensus: Consensus
    redis: Redis
    redis_reader: RedisReader
    webhook_listener: WebhookListener
    logs: Logs
    projects_config_path: str
    indexer_config_path: str
    env: str
    pair_contract_abi: str
    protocol_state: EventContract
    callback_worker_config: CallbackWorkerConfig
    ipfs: IPFSconfig
    anchor_chain_rpc: RPCConfigBase


# Projects related models
class ProcessorConfig(BaseModel):
    module: str
    class_name: str


class ProjectConfig(BaseModel):
    project_type: str
    projects: List[str]
    processor: ProcessorConfig


class ProjectsConfig(BaseModel):
    config: List[ProjectConfig]


# Indexer related models
class IndexingConfig(BaseModel):
    project_type: str
    duration_in_seconds: int


class IndexerConfig(BaseModel):
    config: List[IndexingConfig]
