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


class FullNode(BaseModel):
    url: str
    rate_limit: str


class ArchiveNode(BaseModel):
    url: str
    rate_limit: str


class RPC(BaseModel):
    full_nodes: List[FullNode]
    archive_nodes: Optional[List[ArchiveNode]]
    force_archive_blocks: int
    retry: int
    request_time_out: int
    skip_epoch_threshold_blocks: int


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


class RabbitMQExchange(BaseModel):
    exchange: str


class RabbitMQCallbacks(BaseModel):
    exchange: str


class RabbitMQSetup(BaseModel):
    core: RabbitMQExchange
    callbacks: RabbitMQCallbacks


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


class CallBackWorkerConfig(BaseModel):
    module: str
    class_name: str
    name: str
    num_instances: Optional[int] = 1


class ProjectConfig(BaseModel):
    project_type: str
    projects: List[str]
    workers: List[CallBackWorkerConfig]


class ProjectsConfig(BaseModel):
    config: List[ProjectConfig]


class Settings(BaseModel):
    namespace: str
    core_api: CoreAPI
    chain_id: int
    instance_id: str
    ipfs_url: str
    logs_prune_time: int
    rpc: RPC
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
    env: str
    pair_contract_abi: str
