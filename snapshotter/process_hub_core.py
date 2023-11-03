from datetime import datetime
from distutils import core
import json
import os
from re import S
import resource
import threading
import time
from urllib.parse import urljoin
import uuid
import psutil
import pydantic
import redis
import httpx
from multiprocessing import Process
from signal import SIGCHLD
from signal import SIGINT
from signal import signal
from signal import SIGQUIT
from signal import SIGTERM
from threading import Thread
from typing import Dict
from typing import Optional
from eth_utils.address import to_checksum_address
from snapshotter.processor_distributor import ProcessorDistributor
from snapshotter.settings.config import settings
from snapshotter.system_event_detector import EventDetectorProcess
from snapshotter.utils.aggregation_worker import AggregationAsyncWorker
from snapshotter.utils.callback_helpers import send_failure_notifications_sync
from snapshotter.utils.default_logger import logger
from snapshotter.utils.delegate_worker import DelegateAsyncWorker
from snapshotter.utils.exceptions import SelfExitException
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.helper_functions import cleanup_proc_hub_children
from snapshotter.utils.models.data_models import ProcessorWorkerDetails, SnapshotterEpochProcessingReportItem, SnapshotterIssue, SnapshotterReportState, SnapshotterStateUpdate, SnapshotterStates
from snapshotter.utils.models.data_models import SnapshotterPing
from snapshotter.utils.models.message_models import ProcessHubCommand
from snapshotter.utils.rabbitmq_helpers import RabbitmqSelectLoopInteractor
from snapshotter.utils.redis.redis_conn import REDIS_CONN_CONF, provide_redis_conn_repsawning_thread
from snapshotter.utils.redis.redis_keys import epoch_id_epoch_released_key, epoch_id_project_to_state_mapping
from snapshotter.utils.rpc import RpcHelper
from snapshotter.utils.snapshot_worker import SnapshotAsyncWorker

PROC_STR_ID_TO_CLASS_MAP = {
    'SystemEventDetector': {
        'class': EventDetectorProcess,
        'name': 'Powerloom|SystemEventDetector',
        'target': None,
    },
    'ProcessorDistributor': {
        'class': ProcessorDistributor,
        'name': 'Powerloom|ProcessorDistributor',
        'target': None,
    },
}


class ProcessHubCore(Process):
    _anchor_rpc_helper: RpcHelper
    _redis_connection_pool_sync: redis.BlockingConnectionPool
    _redis_conn_sync: redis.Redis

    def __init__(self, name, **kwargs):
        Process.__init__(self, name=name, **kwargs)
        self._spawned_processes_map: Dict[str, Optional[int]] = dict()  # process name to pid map
        self._spawned_cb_processes_map: Dict[str, Dict[str, Optional[ProcessorWorkerDetails]]] = (
            dict()
        )  # separate map for callback worker spawns. unique ID -> dict(unique_name, pid)
        self._httpx_client = httpx.Client(
            base_url=settings.reporting.service_url,
            limits=httpx.Limits(
                max_keepalive_connections=2,
                max_connections=2,
                keepalive_expiry=300,
            ),
        )
        self._last_reporting_service_ping = 0
        self._last_epoch_processing_health_check = 0
        self._start_time = 0
        self._last_respawn_time = 0
        self._source_chain_block_time = 0
        self._epoch_size = 0
        self._thread_shutdown_event = threading.Event()
        self._shutdown_initiated = False

    def signal_handler(self, signum, frame):
        if signum in [SIGINT, SIGTERM, SIGQUIT]:
            self._shutdown_initiated = True
            if settings.reporting.service_url:
                self._logger.debug('Sending shutdown signal to reporting service')
                send_failure_notifications_sync(
                    client=self._httpx_client,
                    message=SnapshotterIssue(
                        instanceID=settings.instance_id,
                        issueType=SnapshotterReportState.SHUTDOWN_INITIATED.value,
                        projectID='',
                        epochId='',
                        timeOfReporting=datetime.now().isoformat(),
                    )
                )
            self.rabbitmq_interactor.stop()
            # raise GenericExitOnSignal

    def kill_process(self, pid: int):
        p = psutil.Process(pid)
        self._logger.debug(
            'Attempting to send SIGTERM to process ID {} for following command',
            pid,
        )
        p.terminate()
        self._logger.debug('Waiting for 3 seconds to confirm termination of process')
        gone, alive = psutil.wait_procs([p], timeout=3)
        for p_ in alive:
            self._logger.debug(
                'Process ID {} not terminated by SIGTERM. Sending SIGKILL...',
                p_.pid,
            )
            p_.kill()

        for k, v in self._spawned_cb_processes_map.items():
            for unique_worker_entry in v.values():
                if unique_worker_entry is not None and unique_worker_entry.pid == pid:
                    psutil.Process(pid).wait()
                    break

        for k, v in self._spawned_processes_map.items():
            if v is not None and v == pid:
                self._logger.debug('Waiting for process ID {} to join...', pid)
                psutil.Process(pid).wait()
                self._logger.debug('Process ID {} joined...', pid)
                break

    @provide_redis_conn_repsawning_thread
    def internal_state_reporter(self, redis_conn: redis.Redis = None):
        while not self._thread_shutdown_event.wait(timeout=2):
            if self._last_respawn_time == 0 or (self._last_respawn_time != 0 and int(time.time()) - self._last_respawn_time >= 30):
                # allow time for callback workers to fully respawn before writing process table update
                proc_id_map = dict()
                for k, v in self._spawned_processes_map.items():
                    if v:
                        proc_id_map[k] = v
                    else:
                        proc_id_map[k] = -1
                proc_id_map['callback_workers'] = dict()
                for (
                    k,
                    unique_worker_entries,
                ) in self._spawned_cb_processes_map.items():
                    proc_id_map['callback_workers'][k] = dict()
                    for (
                        worker_unique_id,
                        worker_process_details,
                    ) in unique_worker_entries.items():
                        if worker_process_details is not None:
                            proc_id_map['callback_workers'][k][worker_unique_id] = {
                                'pid': worker_process_details.pid,
                                'id': worker_process_details.unique_name,
                            }
                        else:
                            proc_id_map['callback_workers'][k][worker_unique_id] = {
                                'pid': 'null',
                                'id': '',
                            }
                proc_id_map['callback_workers'] = json.dumps(
                    proc_id_map['callback_workers'],
                )
                try:
                    redis_conn.hset(
                        name=f'powerloom:snapshotter:{settings.namespace}:{settings.instance_id}:Processes',
                        mapping=proc_id_map,
                    )
                except Exception as e:
                    self._logger.opt(exception=True).error(
                        'Error while updating process map in redis: {}', e,
                    )
            if settings.reporting.service_url and int(time.time()) - self._last_reporting_service_ping >= 30:
                self._last_reporting_service_ping = int(time.time())
                try:
                    self._httpx_client.post(
                        url=urljoin(settings.reporting.service_url, '/ping'),
                        json=SnapshotterPing(instanceID=settings.instance_id).dict(),
                    )
                except Exception as e:
                    if settings.logs.trace_enabled:
                        self._logger.opt(exception=True).error('Error while pinging reporting service: {}', e,)
                    else:
                        self._logger.error(
                            'Error while pinging reporting service: {}', e,
                        )
            if (self._last_epoch_processing_health_check != 0 and int(time.time()) - self._last_epoch_processing_health_check > 4 * self._source_chain_block_time * self._epoch_size) or \
                    (self._last_epoch_processing_health_check == 0 and self._start_time != 0 and int(time.time()) - self._start_time > 4 * self._source_chain_block_time * self._epoch_size):
                # self._logger.info(
                #     'Skipping epoch processing health check because '
                #     'not enough time has passed for 4 epochs to consider health check since last health check or start time | '
                #     'Start time: {} | Currentime: {} | Source chain block time: {}',
                #     datetime.fromtimestamp(self._start_time).isoformat(),
                #     datetime.now().isoformat(),
                #     self._source_chain_block_time,
                # )
                if not (self._source_chain_block_time != 0 and self._epoch_size != 0):
                    self._logger.info(
                        'Skipping epoch processing health check because source chain block time or epoch size is not known | '
                        'Source chain block time: {} | Epoch size: {}',
                        self._source_chain_block_time,
                        self._epoch_size,
                    )
                    continue
                self._last_epoch_processing_health_check = int(time.time())
                self._logger.debug(
                    'Continuing with epoch processing health check since 4 or more epochs have passed since process start'
                )
                # check for epoch processing status
                try:
                    current_epoch_data = self._protocol_state_contract.functions.currentEpoch().call()
                    current_epoch = {
                        'begin': current_epoch_data[0],
                        'end': current_epoch_data[1],
                        'epochId': current_epoch_data[2],
                    }

                except Exception as e:
                    self._logger.exception(
                        'Exception in get_current_epoch',
                        e=e,
                    )
                    continue
                current_epoch_id = current_epoch['epochId']
                epoch_health = dict()
                # check from previous epoch processing status until 2 further epochs
                for epoch_id in range(current_epoch_id - 1, current_epoch_id - 3 - 1, -1):
                    epoch_specific_report = SnapshotterEpochProcessingReportItem.construct()
                    success_percentage = 0
                    divisor = 1
                    epoch_specific_report.epochId = epoch_id
                    for state in SnapshotterStates:
                        if state not in [SnapshotterStates.SNAPSHOT_BUILD, SnapshotterStates.RELAYER_SEND]:
                            continue
                        state_report_entries = self._redis_conn_sync.hgetall(
                            name=epoch_id_project_to_state_mapping(epoch_id=epoch_id, state_id=state.value),
                        )
                        if state_report_entries:
                            project_state_report_entries = dict()
                            epoch_specific_report.transitionStatus = dict()
                            # epoch_specific_report.transitionStatus[state.value] = dict()
                            project_state_report_entries = {
                                project_id.decode('utf-8'): SnapshotterStateUpdate.parse_raw(project_state_entry)
                                for project_id, project_state_entry in state_report_entries.items()
                            }
                            epoch_specific_report.transitionStatus[state.value] = project_state_report_entries
                            success_percentage += len(
                                [
                                    project_state_report_entry
                                    for project_state_report_entry in project_state_report_entries.values()
                                    if project_state_report_entry.status == 'success'
                                ],
                            ) / len(project_state_report_entries)
                            success_percentage /= divisor
                            divisor += 1
                        else:
                            epoch_specific_report.transitionStatus[state.value] = None
                    if success_percentage != 0:
                        self._logger.debug(
                            'Epoch {} processing success percentage within states {}: {}',
                            list(epoch_specific_report.transitionStatus.keys()),
                            epoch_id,
                            success_percentage * 100,
                        )

                    if any([x is None for x in epoch_specific_report.transitionStatus.values()]):
                        epoch_health[epoch_id] = False
                        self._logger.debug(
                            'Marking epoch {} as unhealthy due to missing state reports against transitions {}',
                            epoch_id,
                            [x for x, y in epoch_specific_report.transitionStatus.items() if y is None],
                        )
                    if success_percentage < 0.5:
                        epoch_health[epoch_id] = False
                        self._logger.debug(
                            'Marking epoch {} as unhealthy due to low success percentage: {}',
                            epoch_id,
                            success_percentage,
                        )
                if len([epoch_id for epoch_id, healthy in epoch_health.items() if not healthy]) >= 2:
                    self._logger.debug(
                        'Sending unhealthy epoch report to reporting service: {}',
                        epoch_health,
                    )
                    send_failure_notifications_sync(
                        client=self._httpx_client,
                        message=SnapshotterIssue(
                            instanceID=settings.instance_id,
                            issueType=SnapshotterReportState.UNHEALTHY_EPOCH_PROCESSING.value,
                            projectID='',
                            epochId='',
                            timeOfReporting=datetime.now().isoformat(),
                            extra=json.dumps(
                                {
                                    'epoch_health': epoch_health,
                                }
                            ),
                        )
                    )
                    self._logger.info('Proceeding to respawn all children because epochs were found unhealthy: {}', epoch_health)
                    self._respawn_all_children()
                    time.sleep(10)
        self._logger.error(
            (
                'Caught thread shutdown notification event. Deleting process'
                ' worker map in redis...'
            ),
        )
        send_failure_notifications_sync(
            client=self._httpx_client,
            message=SnapshotterIssue(
                instanceID=settings.instance_id,
                issueType=SnapshotterReportState.CRASHED_CHILD_WORKER.value,
                projectID='',
                epochId='',
                timeOfReporting=datetime.now().isoformat(),
                extra=json.dumps(
                    {
                        'message': 'internal thread shutdown event caught and deleting process worker map in redis',
                    }
                ),
            )
        )
        redis_conn.delete(
            f'powerloom:snapshotter:{settings.namespace}:{settings.instance_id}:Processes',
        )

    def _kill_all_children(self, core_workers=True):
        self._logger.error('Waiting on spawned callback workers to join...')
        for (
            worker_class_name,
            unique_worker_entries,
        ) in self._spawned_cb_processes_map.items():
            procs = []
            for (
                worker_unique_id,
                worker_unique_process_details,
            ) in unique_worker_entries.items():
                if worker_unique_process_details is not None and worker_unique_process_details.pid:
                    self._logger.error(
                        (
                            'Waiting on spawned callback worker {} | Unique'
                            ' ID {} | PID {}  to join...'
                        ),
                        worker_class_name,
                        worker_unique_id,
                        worker_unique_process_details.pid,
                    )
                    _ = psutil.Process(pid=worker_unique_process_details.pid)
                    procs.append(_)
                    _.terminate()
            gone, alive = psutil.wait_procs(procs, timeout=3)
            for p in alive:
                self._logger.error(
                    'Sending SIGKILL to spawned callback worker {} after not exiting on SIGTERM | PID {}',
                    worker_class_name,
                    p.pid,
                )
                p.kill()
        self._spawned_cb_processes_map = dict()
        if core_workers:
            logger.error(
                'Waiting on spawned core workers to join... {}',
                self._spawned_processes_map,
            )
            procs = []
            for (
                worker_class_name,
                worker_pid,
            ) in self._spawned_processes_map.items():
                self._logger.error(
                    'spawned Process Pid to wait on {}',
                    worker_pid,
                )
                if worker_pid is not None:
                    self._logger.error(
                        (
                            'Waiting on spawned core worker {} | PID {}  to'
                            ' join...'
                        ),
                        worker_class_name,
                        worker_pid,
                    )
                    _ = psutil.Process(worker_pid)
                    procs.append(_)
                    _.terminate()
            gone, alive = psutil.wait_procs(procs, timeout=3)
            for p in alive:
                self._logger.error(
                    'Sending SIGKILL to spawned core worker after not exiting on SIGTERM | PID {}',
                    p.pid,
                )
                p.kill()
            self._spawned_processes_map = dict()

    def _launch_snapshot_cb_workers(self):
        self._logger.debug('=' * 80)
        self._logger.debug('Launching Workers')

        # Starting Snapshot workers
        self._spawned_cb_processes_map['snapshot_workers'] = dict()

        for _ in range(settings.callback_worker_config.num_snapshot_workers):
            unique_id = str(uuid.uuid4())[:5]
            unique_name = (
                f'Powerloom|SnapshotWorker:{settings.namespace}:{settings.instance_id}' +
                '-' +
                unique_id
            )
            snapshot_worker_obj: Process = SnapshotAsyncWorker(name=unique_name)
            snapshot_worker_obj.start()
            self._spawned_cb_processes_map['snapshot_workers'].update(
                {unique_id: ProcessorWorkerDetails(unique_name=unique_name, pid=snapshot_worker_obj.pid)},
            )
            self._logger.debug(
                (
                    'Process Hub Core launched process {} for'
                    ' worker type {} with PID: {}'
                ),
                unique_name,
                'snapshot_workers',
                snapshot_worker_obj.pid,
            )
        # Starting Aggregate workers
        self._spawned_cb_processes_map['aggregation_workers'] = dict()

        for _ in range(settings.callback_worker_config.num_aggregation_workers):
            unique_id = str(uuid.uuid4())[:5]
            unique_name = (
                f'Powerloom|AggregationWorker:{settings.namespace}:{settings.instance_id}' +
                '-' +
                unique_id
            )
            aggregation_worker_obj: Process = AggregationAsyncWorker(name=unique_name)
            aggregation_worker_obj.start()
            self._spawned_cb_processes_map['aggregation_workers'].update(
                {unique_id: ProcessorWorkerDetails(unique_name=unique_name, pid=aggregation_worker_obj.pid)},
            )
            self._logger.debug(
                (
                    'Process Hub Core launched process {} for'
                    ' worker type {} with PID: {}'
                ),
                unique_name,
                'aggregation_workers',
                aggregation_worker_obj.pid,
            )

        # Starting Delegate workers
        self._spawned_cb_processes_map['delegate_workers'] = dict()

        for _ in range(settings.callback_worker_config.num_delegate_workers):
            unique_id = str(uuid.uuid4())[:5]
            unique_name = (
                f'Powerloom|DelegateWorker:{settings.namespace}:{settings.instance_id}' +
                '-' +
                unique_id

            )
            delegate_worker_obj: Process = DelegateAsyncWorker(name=unique_name)
            delegate_worker_obj.start()
            self._spawned_cb_processes_map['delegate_workers'].update(
                {unique_id: ProcessorWorkerDetails(unique_name=unique_name, pid=delegate_worker_obj.pid)},
            )

            self._logger.debug(
                (
                    'Process Hub Core launched process {} for'
                    ' worker type {} with PID: {}'
                ),
                unique_name,
                'delegate_workers',
                delegate_worker_obj.pid,
            )

    def _launch_core_worker(self, proc_name, proc_init_kwargs=dict()):
        try:
            proc_details: dict = PROC_STR_ID_TO_CLASS_MAP[proc_name]
            init_kwargs = dict(name=proc_details['name'])
            init_kwargs.update(proc_init_kwargs)
            if proc_details.get('class'):
                proc_obj = proc_details['class'](**init_kwargs)
                proc_obj.start()
            else:
                proc_obj = Process(
                    target=proc_details['target'],
                    kwargs=proc_init_kwargs,
                )
                proc_obj.start()
            self._logger.debug(
                'Process Hub Core launched process for {} with PID: {}',
                proc_name,
                proc_obj.pid,
            )
            self._spawned_processes_map[proc_name] = proc_obj.pid
        except Exception as err:
            self._logger.opt(exception=True).error(
                'Error while starting process {} | '
                '{}',
                proc_name,
                str(err),
            )

    def _respawn_all_children(self):
        self._kill_all_children()
        self._launch_all_children()
        self._start_time = time.time()
        self._last_respawn_time = int(time.time())

    def _launch_all_children(self):
        self._logger.debug('=' * 80)
        self._logger.debug('Launching Core Workers')
        self._launch_snapshot_cb_workers()
        for proc_name in PROC_STR_ID_TO_CLASS_MAP.keys():
            self._launch_core_worker(proc_name)
        self._launch_snapshot_cb_workers()

    @cleanup_proc_hub_children
    def run(self) -> None:
        self._logger = logger.bind(module='Powerloom|ProcessHub|Core')

        for signame in [SIGINT, SIGTERM, SIGQUIT, SIGCHLD]:
            signal(signame, self.signal_handler)

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (settings.rlimit.file_descriptors, hard),
        )

        self._redis_connection_pool_sync = redis.BlockingConnectionPool(**REDIS_CONN_CONF)
        self._redis_conn_sync = redis.Redis(connection_pool=self._redis_connection_pool_sync)
        self._anchor_rpc_helper = RpcHelper(
            rpc_settings=settings.anchor_chain_rpc
        )
        self._anchor_rpc_helper._load_web3_providers_and_rate_limits()
        protocol_abi = read_json_file(settings.protocol_state.abi, self._logger)
        self._protocol_state_contract = self._anchor_rpc_helper.get_current_node()['web3_client'].eth.contract(
            address=to_checksum_address(
                settings.protocol_state.address,
            ),
            abi=protocol_abi,
        )
        try:
            source_block_time = self._protocol_state_contract.functions.SOURCE_CHAIN_BLOCK_TIME().call()
        except Exception as e:
            self._logger.exception(
                'Exception in querying protocol state for source chain block time: {}',
                e,
            )
        else:
            self._source_chain_block_time = source_block_time / 10 ** 4
            self._logger.debug('Set source chain block time to {}', self._source_chain_block_time)

        try:
            epoch_size = self._protocol_state_contract.functions.EPOCH_SIZE().call()
        except Exception as e:
            self._logger.exception(
                'Exception in querying protocol state for epoch size: {}',
                e,
            )
        else:
            self._epoch_size = epoch_size
        self._launch_snapshot_cb_workers()
        self._logger.debug(
            'Starting Internal Process State reporter for Process Hub Core...',
        )
        self._start_time = time.time()
        self._reporter_thread = Thread(target=self.internal_state_reporter)
        self._reporter_thread.start()
        self._logger.debug('Starting Process Hub Core...')

        queue_name = f'powerloom-processhub-commands-q:{settings.namespace}:{settings.instance_id}'
        self.rabbitmq_interactor: RabbitmqSelectLoopInteractor = RabbitmqSelectLoopInteractor(
            consume_queue_name=queue_name,
            consume_callback=self.callback,
            consumer_worker_name=(
                f'Powerloom|ProcessHub|Core-{settings.instance_id[:5]}'
            ),
        )
        self._logger.debug('Starting RabbitMQ consumer on queue {}', queue_name)
        self.rabbitmq_interactor.run()
        self._logger.debug('RabbitMQ interactor ioloop ended...')
        self._thread_shutdown_event.set()
        raise SelfExitException

    def callback(self, dont_use_ch, method, properties, body):
        self.rabbitmq_interactor._channel.basic_ack(
            delivery_tag=method.delivery_tag,
        )
        command = json.loads(body)
        try:
            cmd_json = ProcessHubCommand(**command)
        except pydantic.ValidationError:
            self._logger.error('ProcessHubCore received unrecognized command')
            self._logger.error(command)
            return

        if cmd_json.command == 'stop':
            self._logger.debug(
                'Process Hub Core received stop command: {}', cmd_json,
            )
            process_id = cmd_json.pid
            proc_str_id = cmd_json.proc_str_id
            if process_id:
                return
            if proc_str_id:
                if proc_str_id == 'self':
                    return
                    # self._logger.error('Received stop command on self. Initiating shutdown...')
                    # raise SelfExitException
                mapped_pid = self._spawned_processes_map.get(proc_str_id)
                if not mapped_pid:
                    self._logger.error(
                        (
                            'Did not find process ID in core processes string'
                            ' map: {}'
                        ),
                        proc_str_id,
                    )
                    for (
                        cb_worker_type,
                        unique_worker_entries,
                    ) in self._spawned_cb_processes_map.items():
                        if cb_worker_type == proc_str_id:
                            for (
                                worker_unique_id,
                                worker_process_details,
                            ) in unique_worker_entries.items():
                                if worker_process_details is not None and worker_process_details.pid is not None:
                                    self.kill_process(worker_process_details.pid)
                                    self._spawned_cb_processes_map[
                                        cb_worker_type
                                    ][worker_unique_id] = ProcessorWorkerDetails(
                                        unique_name=worker_unique_id, pid=None,
                                    )
                                    self._logger.info(
                                        'Killing process ID {} for callback process {} with identifier {}',
                                        worker_process_details.pid, proc_str_id, worker_unique_id,
                                    )
                else:
                    self.kill_process(mapped_pid)
                    self._spawned_processes_map[proc_str_id] = None

        elif cmd_json.command == 'start':
            self._logger.debug(
                'Process Hub Core received start command: {}', cmd_json,
            )
            proc_name = cmd_json.proc_str_id
            if not proc_name:
                self._logger.error(
                    'Received start command without process name',
                )
                return
            if proc_name not in PROC_STR_ID_TO_CLASS_MAP.keys():
                self._logger.error(
                    'Received unrecognized process name to start: {}', proc_name,
                )
                return
            self._logger.debug(
                'Process Hub Core launching process for {}', proc_name,
            )
            self._launch_core_worker(proc_name, cmd_json.init_kwargs)

        elif cmd_json.command == 'restart':
            try:
                self._logger.debug(
                    'Process Hub Core received restart command: {}', cmd_json,
                )
                # first kill
                self._logger.debug(
                    'Attempting to kill process: {}', cmd_json.pid,
                )
                self.kill_process(cmd_json.pid)
                self._logger.debug(
                    'Attempting to start process: {}', cmd_json.proc_str_id,
                )
            except Exception as err:
                self._logger.opt(exception=True).error(
                    (
                        f'Error while restarting a process:{cmd_json} |'
                        f' error_msg: {str(err)}'
                    ),
                )
        elif cmd_json.command == 'respawn':
            self._respawn_all_children()


if __name__ == '__main__':
    p = ProcessHubCore(name='Powerloom|SnapshotterProcessHub|Core')
    p.start()
    while p.is_alive():
        logger.debug(
            'Process hub core is still alive. waiting on it to join...',
        )
        try:
            p.join()
        except:
            pass
