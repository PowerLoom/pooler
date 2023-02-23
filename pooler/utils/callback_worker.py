import asyncio
import importlib
import json
import multiprocessing
import resource
import signal
import time
from functools import partial
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union
from uuid import uuid4

from aio_pika import IncomingMessage
from aio_pika.pool import Pool
from eth_utils import keccak
from httpx import AsyncClient
from httpx import AsyncHTTPTransport
from httpx import Limits
from httpx import Timeout
from pydantic import ValidationError
from redis import asyncio as aioredis
from setproctitle import setproctitle

from pooler.settings.config import projects_config
from pooler.settings.config import settings
from pooler.utils.callback_helpers import AuditProtocolCommandsHelper
from pooler.utils.callback_helpers import get_rabbitmq_channel
from pooler.utils.callback_helpers import get_rabbitmq_connection
from pooler.utils.callback_helpers import notify_on_task_failure
from pooler.utils.default_logger import logger
from pooler.utils.models.data_models import PayloadCommitAPIRequest
from pooler.utils.models.data_models import SnapshotterIssue
from pooler.utils.models.data_models import SnapshotterIssueSeverity
from pooler.utils.models.data_models import SourceChainDetails
from pooler.utils.models.message_models import PowerloomCallbackProcessMessage
from pooler.utils.models.message_models import SnapshotBase
from pooler.utils.redis.rate_limiter import load_rate_limiter_scripts
from pooler.utils.redis.redis_conn import RedisPoolCache
from pooler.utils.redis.redis_keys import (
    cb_broadcast_processing_logs_zset,
)
from pooler.utils.redis.redis_keys import discarded_query_epochs_redis_q
from pooler.utils.redis.redis_keys import failed_query_epochs_redis_q
from pooler.utils.rpc import RpcHelper


class CallbackAsyncWorker(multiprocessing.Process):

    def __init__(self, name, **kwargs):
        self._core_rmq_consumer: asyncio.Task
        self._q = f'powerloom-backend-cb:{settings.namespace}:{settings.instance_id}'
        self._rmq_routing = f'powerloom-backend-callback:{settings.namespace}:{settings.instance_id}.*'
        self._unique_id = f'{name}-' + keccak(text=str(uuid4())).hex()[:8]
        self._aioredis_pool = None
        self._redis_conn: Union[None, aioredis.Redis] = None
        self._running_callback_tasks: Dict[str, asyncio.Task] = dict()
        super(CallbackAsyncWorker, self).__init__(name=name, **kwargs)
        self._logger = logger.bind(module=self.name)

        self._rate_limiting_lua_scripts = None
        self._client = None
        self._async_transport = None
        self._shutdown_signal_received_count = 0
        self._rpc_helper = None
        self._project_calculation_mapping = None

    async def _shutdown_handler(self, sig, loop: asyncio.AbstractEventLoop):
        self._shutdown_signal_received_count += 1
        if self._shutdown_signal_received_count > 1:
            self._logger.info(
                (
                    f'Received exit signal {sig.name}. Not processing as'
                    ' shutdown sequence was already initiated...'
                ),
            )
        else:
            self._logger.info(
                (
                    f'Received exit signal {sig.name}. Processing shutdown'
                    ' sequence...'
                ),
            )
            # check the done or cancelled status of self._running_callback_tasks.values()
            for u_uid, t in self._running_callback_tasks.items():
                self._logger.debug(
                    (
                        'Shutdown handler: Checking result and status of'
                        ' aio_pika consumer callback task {}'
                    ),
                    t.get_name(),
                )
                try:
                    task_result = t.result()
                except asyncio.CancelledError:
                    self._logger.info(
                        (
                            'Shutdown handler: aio_pika consumer callback task'
                            ' {} was cancelled'
                        ),
                        t.get_name(),
                    )
                except asyncio.InvalidStateError:
                    self._logger.info(
                        (
                            'Shutdown handler: aio_pika consumer callback task'
                            ' {} result not available yet. Still running.'
                        ),
                        t.get_name(),
                    )
                except Exception as e:
                    self._logger.info(
                        (
                            'Shutdown handler: aio_pika consumer callback task'
                            ' {} raised Exception. {}'
                        ),
                        t.get_name(),
                        e,
                    )
                else:
                    self._logger.info(
                        (
                            'Shutdown handler: aio_pika consumer callback task'
                            ' returned with result {}'
                        ),
                        t.get_name(),
                        task_result,
                    )

            tasks = [
                t
                for t in asyncio.all_tasks(loop)
                if t is not asyncio.current_task(loop)
            ]

            [task.cancel() for task in tasks]

            self._logger.info(f'Cancelling {len(tasks)} outstanding tasks')
            await asyncio.gather(*tasks, return_exceptions=True)
            loop.stop()
            self._logger.info('Shutdown complete.')

    @notify_on_task_failure
    async def _processor_task(self, msg_obj: PowerloomCallbackProcessMessage, task_type: str):
        """Function used to process the received message object."""
        self._logger.debug(
            'Processing callback: {}', msg_obj,
        )

        await self.init()

        if task_type not in self._project_calculation_mapping:
            self._logger.error(
                (
                    'No project calculation mapping found for task type'
                    f' {task_type}. Skipping...'
                ),
            )
            return

        self_unique_id = str(uuid4())
        cur_task: asyncio.Task = asyncio.current_task(
            asyncio.get_running_loop(),
        )
        cur_task.set_name(
            f'aio_pika.consumer|Processor|{task_type}|{msg_obj.contract}',
        )
        self._running_callback_tasks[self_unique_id] = cur_task

        if not self._rate_limiting_lua_scripts:
            self._rate_limiting_lua_scripts = await load_rate_limiter_scripts(
                self._redis_conn,
            )
        self._logger.debug(
            'Got epoch to process for {}: {}',
            task_type, msg_obj,
        )

        # check for enqueued failed query epochs
        epochs = await self._prepare_epochs(
            failed_query_epochs_key=failed_query_epochs_redis_q.format(
                task_type, msg_obj.contract,
            ),
            discarded_query_epochs_key=discarded_query_epochs_redis_q.format(
                task_type, msg_obj.contract,
            ),
            current_epoch=msg_obj,
            failed_query_epochs_l=[],
            stream=task_type,
        )

        stream_processor = self._project_calculation_mapping[task_type]
        epoch_snapshot_map = await self._map_processed_epochs_to_adapters(
            epochs=epochs,
            cb_fn_async=stream_processor.compute,
            enqueue_on_failure=True,
            data_source_contract_address=msg_obj.contract,
            failed_query_epochs_key=failed_query_epochs_redis_q.format(
                task_type, msg_obj.contract,
            ),
            transformation_lambdas=stream_processor.transformation_lambdas,
        )

        await self._send_audit_payload_commit_service(
            audit_stream=task_type,
            original_epoch=msg_obj,
            epoch_snapshot_map=epoch_snapshot_map,
        )

        del self._running_callback_tasks[self_unique_id]

    async def _send_audit_payload_commit_service(
        self,
        audit_stream,
        original_epoch: PowerloomCallbackProcessMessage,
        epoch_snapshot_map: Dict[
            Tuple[int, int],
            Union[SnapshotBase, None],
        ],
    ):
        for each_epoch, epoch_snapshot in epoch_snapshot_map.items():
            if not epoch_snapshot:
                self._logger.error(
                    (
                        'No epoch snapshot to commit. Construction of snapshot'
                        ' failed for {} against epoch {}'
                    ),
                    audit_stream,
                    each_epoch,
                )
                # TODO: standardize/unify update log data model
                update_log = {
                    'worker': self._unique_id,
                    'update': {
                        'action': f'SnapshotBuild-{audit_stream}',
                        'info': {
                            'original_epoch': original_epoch.dict(),
                            'cur_epoch': {
                                'begin': each_epoch[0],
                                'end': each_epoch[1],
                            },
                            'status': 'Failed',
                        },
                    },
                }

                await self._redis_conn.zadd(
                    name=cb_broadcast_processing_logs_zset.format(
                        original_epoch.broadcast_id,
                    ),
                    mapping={json.dumps(update_log): int(time.time())},
                )
            else:
                update_log = {
                    'worker': self._unique_id,
                    'update': {
                        'action': f'SnapshotBuild-{audit_stream}',
                        'info': {
                            'original_epoch': original_epoch.dict(),
                            'cur_epoch': {
                                'begin': each_epoch[0],
                                'end': each_epoch[1],
                            },
                            'status': 'Success',
                            'snapshot': epoch_snapshot.dict(),
                        },
                    },
                }

                await self._redis_conn.zadd(
                    name=cb_broadcast_processing_logs_zset.format(
                        original_epoch.broadcast_id,
                    ),
                    mapping={json.dumps(update_log): int(time.time())},
                )
                source_chain_details = SourceChainDetails(
                    chainID=settings.chain_id,
                    epochStartHeight=each_epoch[0],
                    epochEndHeight=each_epoch[1],
                )
                payload = epoch_snapshot.dict()
                project_id = f'{audit_stream}_{original_epoch.contract}_{settings.namespace}'

                commit_payload = PayloadCommitAPIRequest(
                    projectId=project_id,
                    payload=payload,
                    sourceChainDetails=source_chain_details,
                )

                try:
                    r = await AuditProtocolCommandsHelper.commit_payload(
                        report_payload=commit_payload,
                        session=self._client,
                    )
                except Exception as e:
                    self._logger.opt(exception=True).error(
                        (
                            'Exception committing snapshot to audit protocol:'
                            ' {} | dump: {}'
                        ),
                        epoch_snapshot,
                        e,
                    )
                    update_log = {
                        'worker': self._unique_id,
                        'update': {
                            'action': f'SnapshotCommit-{audit_stream}',
                            'info': {
                                'snapshot': payload,
                                'original_epoch': original_epoch.dict(),
                                'cur_epoch': {
                                    'begin': each_epoch[0],
                                    'end': each_epoch[1],
                                },
                                'status': 'Failed',
                                'exception': e,
                            },
                        },
                    }

                    await self._redis_conn.zadd(
                        name=cb_broadcast_processing_logs_zset.format(
                            original_epoch.broadcast_id,
                        ),
                        mapping={json.dumps(update_log): int(time.time())},
                    )
                else:
                    self._logger.debug(
                        (
                            'Sent snapshot to audit protocol payload commit'
                            ' service: {} | Response: {}, Time: {}'
                        ),
                        commit_payload,
                        r,
                        int(time.time()),
                    )
                    update_log = {
                        'worker': self._unique_id,
                        'update': {
                            'action': f'SnapshotCommit-{audit_stream}',
                            'info': {
                                'snapshot': payload,
                                'original_epoch': original_epoch.dict(),
                                'cur_epoch': {
                                    'begin': each_epoch[0],
                                    'end': each_epoch[1],
                                },
                                'status': 'Success',
                                'response': r,
                            },
                        },
                    }

                    await self._redis_conn.zadd(
                        name=cb_broadcast_processing_logs_zset.format(
                            original_epoch.broadcast_id,
                        ),
                        mapping={json.dumps(update_log): int(time.time())},
                    )

    async def _prepare_epochs(
        self,
        failed_query_epochs_key: str,
        stream: str,
        discarded_query_epochs_key: str,
        current_epoch: PowerloomCallbackProcessMessage,
        failed_query_epochs_l: Optional[List],
    ) -> List[PowerloomCallbackProcessMessage]:
        queued_epochs = list()
        # checks for any previously queued epochs, returns a list of such epochs in increasing order of blockheights
        if settings.env != 'test':
            project_id = (
                f'{stream}_{current_epoch.contract}_{settings.namespace}'
            )
            fall_behind_reset_threshold = (
                settings.rpc.skip_epoch_threshold_blocks
            )
            failed_query_epochs = await self._redis_conn.lpop(
                failed_query_epochs_key,
            )
            while failed_query_epochs:
                epoch_broadcast: PowerloomCallbackProcessMessage = (
                    PowerloomCallbackProcessMessage.parse_raw(
                        failed_query_epochs.decode('utf-8'),
                    )
                )
                if (
                    current_epoch.begin - epoch_broadcast.end >
                    fall_behind_reset_threshold
                ):
                    # send alert
                    await self._client.post(
                        url=settings.issue_report_url,
                        json=SnapshotterIssue(
                            instanceID=settings.instance_id,
                            severity=SnapshotterIssueSeverity.medium,
                            issueType='SKIP_QUEUED_EPOCH',
                            projectID=project_id,
                            epochs=[epoch_broadcast.end],
                            timeOfReporting=int(time.time()),
                            serviceName=f'Pooler|CallbackProcessor|{stream}',
                        ).dict(),
                    )
                    await self._redis_conn.rpush(
                        discarded_query_epochs_key,
                        epoch_broadcast.json(),
                    )
                    self._logger.warning(
                        (
                            'Project {} | QUEUED Epoch {} processing has fallen'
                            ' behind by more than {} blocks, alert sent to DAG'
                            ' Verifier | Discarding queued epoch'
                        ),
                        project_id,
                        epoch_broadcast,
                        fall_behind_reset_threshold,
                    )
                else:
                    self._logger.info(
                        (
                            'Found queued epoch against which snapshot'
                            " construction for pair contract's {} failed"
                            ' earlier: {}'
                        ),
                        stream,
                        epoch_broadcast,
                    )
                    queued_epochs.append(epoch_broadcast)
                failed_query_epochs = await self._redis_conn.lpop(
                    failed_query_epochs_key,
                )
        else:
            queued_epochs = (
                failed_query_epochs_l if failed_query_epochs_l else list()
            )
        queued_epochs.append(current_epoch)
        # check for continuity in epochs before ordering them
        self._logger.info(
            (
                'Attempting to check for continuity in queued epochs to'
                " generate snapshots against pair contract's {} including"
                ' current epoch: {}'
            ),
            stream,
            queued_epochs,
        )
        continuity = True
        for idx, each_epoch in enumerate(queued_epochs):
            if idx == 0:
                continue
            if each_epoch.begin != queued_epochs[idx - 1].end + 1:
                continuity = False
                break
        if not continuity:
            # mark others as discarded
            discarded_epochs = queued_epochs[:-1]
            # pop off current epoch added to end of this list
            queued_epochs = [queued_epochs[-1]]
            self._logger.info(
                (
                    'Recording epochs as discarded during snapshot construction'
                    ' stage for {}: {}'
                ),
                stream,
                queued_epochs,
            )
            for x in discarded_epochs:
                await self._redis_conn.rpush(
                    discarded_query_epochs_key,
                    x.json(),
                )
        return queued_epochs

    async def _map_processed_epochs_to_adapters(
        self,
        epochs: List[PowerloomCallbackProcessMessage],
        cb_fn_async,
        enqueue_on_failure,
        data_source_contract_address,
        failed_query_epochs_key,
        transformation_lambdas: List[Callable],
    ):
        try:
            tasks_map = dict()
            for each_epoch in epochs:
                tasks_map[
                    (
                        each_epoch.begin,
                        each_epoch.end,
                        each_epoch.broadcast_id,
                    )
                ] = cb_fn_async(
                    min_chain_height=each_epoch.begin,
                    max_chain_height=each_epoch.end,
                    data_source_contract_address=data_source_contract_address,
                    redis_conn=self._redis_conn,
                    rpc_helper=self._rpc_helper,
                )
            results = await asyncio.gather(
                *tasks_map.values(), return_exceptions=True,
            )
            results_map = dict()
            for idx, each_result in enumerate(results):
                epoch_against_result = list(tasks_map.keys())[idx]
                if (
                    isinstance(each_result, Exception) and
                    enqueue_on_failure and
                    settings.env != 'test'
                ):
                    queue_msg_obj = PowerloomCallbackProcessMessage(
                        begin=epoch_against_result[0],
                        end=epoch_against_result[1],
                        broadcast_id=epoch_against_result[2],
                        contract=data_source_contract_address,
                    )
                    await self._redis_conn.rpush(
                        failed_query_epochs_key,
                        queue_msg_obj.json(),
                    )
                    self._logger.debug(
                        (
                            'Enqueued epoch broadcast ID {} because reserve query'
                            ' failed on {} - {} | Exception: {}'
                        ),
                        queue_msg_obj.broadcast_id,
                        epoch_against_result[0],
                        epoch_against_result[1],
                        each_result,
                    )
                    results_map[
                        (epoch_against_result[0], epoch_against_result[1])
                    ] = None
                else:
                    if not isinstance(each_result, Exception):
                        for transformation in transformation_lambdas:
                            each_result = transformation(
                                each_result,
                                data_source_contract_address,
                                epoch_against_result[0],
                                epoch_against_result[1],
                            )
                        results_map[
                            (
                                epoch_against_result[0],
                                epoch_against_result[1],
                            )
                        ] = each_result
                return results_map

        except Exception as e:
            self._logger.opt(exception=True).exception(
                'Exception while mapping processed epochs to adapters: {}',
                e,
            )
            return None

    async def _update_broadcast_processing_status(
        self, broadcast_id, update_state,
    ):
        await self._redis_conn.hset(
            cb_broadcast_processing_logs_zset.format(self.name),
            broadcast_id,
            json.dumps(update_state),
        )

    async def _rabbitmq_consumer(self, loop):
        self._rmq_connection_pool = Pool(get_rabbitmq_connection, max_size=5, loop=loop)
        self._rmq_channel_pool = Pool(
            partial(get_rabbitmq_channel, self._rmq_connection_pool), max_size=20,
            loop=loop,
        )
        async with self._rmq_channel_pool.acquire() as channel:
            await channel.set_qos(20)
            q_obj = await channel.get_queue(
                name=self._q,
                ensure=False,
            )
            self._logger.debug(
                f'Consuming queue {self._q} with routing key {self._rmq_routing}...',
            )
            await q_obj.consume(self._on_rabbitmq_message)

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        task_type = message.routing_key.split('.')[-1]
        self._logger.debug('task type: {}', task_type)
        await message.ack()

        try:
            msg_obj: PowerloomCallbackProcessMessage = (
                PowerloomCallbackProcessMessage.parse_raw(message.body)
            )
        except ValidationError as e:
            self._logger.opt(exception=True).error(
                (
                    'Bad message structure of callback processor. Error: {}'
                ),
                e,
            )
            return
        except Exception as e:
            self._logger.opt(exception=True).error(
                (
                    'Unexpected message structure of callback in processor. Error: {}'
                ),
                e,
            )
            return

        asyncio.ensure_future(self._processor_task(msg_obj=msg_obj, task_type=task_type))

    async def _init_redis_pool(self):
        if self._aioredis_pool is not None:
            return
        self._aioredis_pool = RedisPoolCache()
        await self._aioredis_pool.populate()
        self._redis_conn = self._aioredis_pool._aioredis_pool

    async def _init_httpx_client(self):
        if self._client is not None:
            return
        self._async_transport = AsyncHTTPTransport(
            limits=Limits(
                max_connections=100,
                max_keepalive_connections=50,
                keepalive_expiry=None,
            ),
        )
        self._client = AsyncClient(
            timeout=Timeout(timeout=5.0),
            follow_redirects=False,
            transport=self._async_transport,
        )

    async def _init_rpc_helper(self):
        if self._rpc_helper is not None:
            return
        self._rpc_helper = RpcHelper()

    async def _init_project_calculation_mapping(self):
        if self._project_calculation_mapping is not None:
            return
        # Generate project function mapping
        self._project_calculation_mapping = dict()
        for project_config in projects_config:
            key = project_config.project_type
            if key in self._project_calculation_mapping:
                raise Exception('Duplicate project type found')
            module = importlib.import_module(project_config.processor.module)
            class_ = getattr(module, project_config.processor.class_name)
            self._project_calculation_mapping[key] = class_()

    async def init(self):
        await self._init_redis_pool()
        await self._init_httpx_client()
        await self._init_rpc_helper()
        await self._init_project_calculation_mapping()

    def run(self) -> None:
        setproctitle(self._unique_id)
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (settings.rlimit.file_descriptors, hard),
        )
        # logging.config.dictConfig(config_logger_with_namespace(self.name))
        ev_loop = asyncio.get_event_loop()
        signals = (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT)
        for s in signals:
            ev_loop.add_signal_handler(
                s,
                lambda x=s: ev_loop.create_task(
                    self._shutdown_handler(x, ev_loop),
                ),
            )
        self._logger.debug(
            f'Starting asynchronous epoch callback worker {self._unique_id}...',
        )
        self._core_rmq_consumer = asyncio.ensure_future(
            self._rabbitmq_consumer(ev_loop),
        )
        try:
            ev_loop.run_forever()
        finally:
            ev_loop.close()
