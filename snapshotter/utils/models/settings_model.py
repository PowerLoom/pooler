from enum import Enum
from typing import List
from typing import Optional
from typing import Union

from ipfs_client.settings.data_models import IPFSConfig
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


class QueueConfig(BaseModel):
    num_instances: int


class RabbitMQConfig(BaseModel):
    exchange: str


class RabbitMQSetup(BaseModel):
    core: RabbitMQConfig
    callbacks: RabbitMQConfig
    event_detector: RabbitMQConfig
    commit_payload: RabbitMQConfig
    delegated_worker: RabbitMQConfig


class RabbitMQ(BaseModel):
    user: str
    password: str
    host: str
    port: int
    setup: RabbitMQSetup


class ReportingConfig(BaseModel):
    slack_url: str
    service_url: str


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


class Logs(BaseModel):
    trace_enabled: bool
    write_to_files: bool


class EventContract(BaseModel):
    address: str
    abi: str


class CallbackWorkerConfig(BaseModel):
    num_snapshot_workers: int
    num_aggregation_workers: int
    num_delegate_workers: int


class IPFSWriterRateLimit(BaseModel):
    req_per_sec: int
    burst: int


class ExternalAPIAuth(BaseModel):
    # this is most likely used as a basic auth tuple of (username, password)
    apiKey: str
    apiSecret: str = ''


class Web3Storage(BaseModel):
    upload_snapshots: bool
    upload_aggregates: bool
    url: str
    upload_url_suffix: str
    api_token: str
    timeout: int
    max_idle_conns: int
    idle_conn_timeout: int
    # rate_limit: Optional[IPFSWriterRateLimit] = None


class Settings(BaseModel):
    namespace: str
    core_api: CoreAPI
    instance_id: str
    rpc: RPCConfigFull
    rlimit: RLimit
    rabbitmq: RabbitMQ
    reporting: ReportingConfig
    redis: Redis
    redis_reader: RedisReader
    logs: Logs
    projects_config_path: str
    preloader_config_path: str
    pair_contract_abi: str
    aggregator_config_path: str
    protocol_state: EventContract
    callback_worker_config: CallbackWorkerConfig
    ipfs: IPFSConfig
    web3storage: Web3Storage
    anchor_chain_rpc: RPCConfigBase


# Projects related models
class ProcessorConfig(BaseModel):
    module: str
    class_name: str


class ProjectConfig(BaseModel):
    project_type: str
    projects: Optional[List[str]] = None
    processor: ProcessorConfig
    preload_tasks: List[str]
    bulk_mode: Optional[bool] = False


class ProjectsConfig(BaseModel):
    config: List[ProjectConfig]


class AggregateFilterConfig(BaseModel):
    projectId: str


class AggregateOn(str, Enum):
    single_project = 'SingleProject'
    multi_project = 'MultiProject'


class AggregationConfig(BaseModel):
    project_type: str
    aggregate_on: AggregateOn
    filters: Optional[AggregateFilterConfig]
    projects_to_wait_for: Optional[List[str]]
    processor: ProcessorConfig


class AggregatorConfig(BaseModel):
    config: List[AggregationConfig]


class Preloader(BaseModel):
    task_type: str
    module: str
    class_name: str


class DelegatedTask(BaseModel):
    task_type: str
    module: str
    class_name: str


class PreloaderConfig(BaseModel):
    preloaders: List[Preloader]
    delegate_tasks: List[DelegatedTask]
    timeout: int
