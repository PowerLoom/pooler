from datetime import datetime
import json
import os
import threading
from urllib.parse import urljoin
import uuid
from multiprocessing import Process
from signal import SIGCHLD
from signal import SIGINT
from signal import signal
from signal import SIGQUIT
from signal import SIGTERM
from threading import Thread
from typing import Dict
from typing import Optional
import httpx

import psutil
import pydantic
import redis

from snapshotter.processor_distributor import ProcessorDistributor
from snapshotter.settings.config import settings
from snapshotter.system_event_detector import EventDetectorProcess
from snapshotter.utils.aggregation_worker import AggregationAsyncWorker
from snapshotter.utils.callback_helpers import send_failure_notifications_sync
from snapshotter.utils.default_logger import logger
from snapshotter.utils.delegate_worker import DelegateAsyncWorker
from snapshotter.utils.exceptions import SelfExitException
from snapshotter.utils.helper_functions import cleanup_proc_hub_children
from snapshotter.utils.models.data_models import ProcessorWorkerDetails, SnapshotterIssue, SnapshotterReportState
from snapshotter.utils.models.data_models import SnapshotWorkerDetails
from snapshotter.utils.models.data_models import SnapshotterPing
from snapshotter.utils.models.message_models import ProcessHubCommand
from snapshotter.utils.rabbitmq_helpers import RabbitmqSelectLoopInteractor
from snapshotter.utils.redis.redis_conn import provide_redis_conn
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
    def __init__(self, name, **kwargs):
        Process.__init__(self, name=name, **kwargs)
        self._spawned_processes_map: Dict[str, Optional[int]] = dict()  # process name to pid map
        self._spawned_cb_processes_map: Dict[str, Dict[str, Optional[SnapshotWorkerDetails]]] = (
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
        self._thread_shutdown_event = threading.Event()
        self._shutdown_initiated = False

    def signal_handler(self, signum, frame):
        if signum == SIGCHLD and not self._shutdown_initiated:
            pid, status = os.waitpid(
                -1, os.WNOHANG | os.WUNTRACED | os.WCONTINUED,
            )
            if os.WIFCONTINUED(status) or os.WIFSTOPPED(status):
                return
            if os.WIFSIGNALED(status) or os.WIFEXITED(status):
                self._logger.debug(
                    (
                        'Received process crash notification for child process'
                        ' PID: {}'
                    ),
                    pid,
                )
                callback_worker_module_file = None
                callback_worker_class = None
                callback_worker_name = None
                callback_worker_unique_id = None
                for (
                    cb_worker_type,
                    worker_unique_id_entries,
                ) in self._spawned_cb_processes_map.items():
                    for (
                        unique_id,
                        worker_process_details,
                    ) in worker_unique_id_entries.items():
                        if worker_process_details is not None and worker_process_details.pid == pid:
                            self._logger.debug(
                                (
                                    'Found crashed child process PID in spawned'
                                    ' callback workers | Callback worker class:'
                                    ' {} | Unique worker identifier: {}'
                                ),
                                cb_worker_type,
                                worker_process_details.unique_name,
                            )
                            callback_worker_name = worker_process_details.unique_name
                            callback_worker_unique_id = unique_id
                            callback_worker_class = cb_worker_type
                            
                            break

                if (
                    callback_worker_name and
                    callback_worker_unique_id and callback_worker_class
                ):

                    if callback_worker_class == 'snapshot_workers':
                        worker_obj: Process = SnapshotAsyncWorker(
                            name=callback_worker_name,
                        )
                    elif callback_worker_class == 'aggregation_workers':
                        worker_obj: Process = AggregationAsyncWorker(
                            name=callback_worker_name,
                        )

                    elif callback_worker_class == 'delegate_workers':
                        worker_obj: Process = DelegateAsyncWorker(
                            name=callback_worker_name,
                        )

                    worker_obj.start()
                    self._spawned_cb_processes_map[callback_worker_class][callback_worker_unique_id] = \
                        SnapshotWorkerDetails(unique_name=callback_worker_unique_id, pid=worker_obj.pid)
                    self._logger.debug(
                        (
                            'Respawned callback worker class {} unique ID {}'
                            ' with PID {} after receiving crash signal against'
                            ' PID {}'
                        ),
                        callback_worker_class,
                        callback_worker_unique_id,
                        worker_obj.pid,
                        pid,
                    )
                    if settings.reporting.service_url:
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
                                        'worker_name': callback_worker_name,
                                        'pid': pid,
                                        'worker_class': callback_worker_class,
                                        'worker_unique_id': callback_worker_unique_id,
                                        'respawned_pid': worker_obj.pid,
                                    }
                                ),
                            )
                        )
                    return

                for cb_worker_type, worker_pid in self._spawned_processes_map.items():
                    if worker_pid is not None and worker_pid == pid:
                        self._logger.debug('RESPAWNING: process for {}', cb_worker_type)
                        proc_details: dict = PROC_STR_ID_TO_CLASS_MAP.get(cb_worker_type)
                        init_kwargs = dict(name=proc_details['name'])
                        if proc_details.get('class'):
                            proc_obj = proc_details['class'](**init_kwargs)
                            proc_obj.start()
                        else:
                            proc_obj = Process(target=proc_details['target'])
                            proc_obj.start()
                        self._logger.debug(
                            'RESPAWNED: process for {} with PID: {}',
                            cb_worker_type,
                            proc_obj.pid,
                        )
                        self._spawned_processes_map[cb_worker_type] = proc_obj.pid
        elif signum in [SIGINT, SIGTERM, SIGQUIT]:
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

        for k, v in self._spawned_processes_map.items():
            if v is not None and v == pid:
                self._logger.debug('Waiting for process ID {} to join...', pid)
                psutil.Process(pid).wait()
                self._logger.debug('Process ID {} joined...', pid)

    @provide_redis_conn
    def internal_state_reporter(self, redis_conn: redis.Redis = None):
        while not self._thread_shutdown_event.wait(timeout=2):
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
            redis_conn.hset(
                name=f'powerloom:snapshotter:{settings.namespace}:{settings.instance_id}:Processes',
                mapping=proc_id_map,
            )
            if settings.reporting.service_url:
                self._httpx_client.post(
                    url=urljoin(settings.reporting.service_url, '/ping'),
                    json=SnapshotterPing(instanceID=settings.instance_id).dict(),
                )
        self._logger.error(
            (
                'Caught thread shutdown notification event. Deleting process'
                ' worker map in redis...'
            ),
        )
        redis_conn.delete(
            f'powerloom:snapshotter:{settings.namespace}:{settings.instance_id}:Processes',
        )

    @cleanup_proc_hub_children
    def run(self) -> None:
        self._logger = logger.bind(module='Powerloom|ProcessHub|Core')

        for signame in [SIGINT, SIGTERM, SIGQUIT, SIGCHLD]:
            signal(signame, self.signal_handler)

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
                    'Process Hub Core launched process {} for snapshot'
                    ' worker {} with PID: {}'
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
                    ' worker {} with PID: {}'
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
                    ' worker {} with PID: {}'
                ),
                unique_name,
                'delegate_workers',
                delegate_worker_obj.pid,
            )

        self._logger.debug(
            'Starting Internal Process State reporter for Process Hub Core...',
        )
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
                                    ][worker_unique_id] = SnapshotWorkerDetails(
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
            try:
                self._logger.debug(
                    'Process Hub Core received start command: {}', cmd_json,
                )
                proc_name = cmd_json.proc_str_id
                self._logger.debug(
                    'Process Hub Core launching process for {}', proc_name,
                )
                proc_details: dict = PROC_STR_ID_TO_CLASS_MAP.get(proc_name)
                init_kwargs = dict(name=proc_details['name'])
                init_kwargs.update(cmd_json.init_kwargs)
                if proc_details.get('class'):
                    proc_obj = proc_details['class'](**init_kwargs)
                    proc_obj.start()
                else:
                    proc_obj = Process(
                        target=proc_details['target'],
                        kwargs=cmd_json.init_kwargs,
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
                    (
                        f'Error while starting a process:{cmd_json} |'
                        f' error_msg: {str(err)}'
                    ),
                )
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
