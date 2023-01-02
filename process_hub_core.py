import threading
import uuid
from exceptions import SelfExitException
from redis_conn import provide_redis_conn
from threading import Thread
from multiprocessing import Process
from typing import Dict, Union
from dynaconf import settings
from message_models import ProcessHubCommand
from helper_functions import cleanup_children_procs
from epoch_broadcast_callback_manager import EpochCallbackManager
from system_epoch_detector import EpochDetectorProcess
import redis
import pydantic
import psutil
import logging
import logging.handlers
import importlib
import json
from setproctitle import setproctitle
from signal import signal, SIGINT, SIGTERM, SIGQUIT, SIGCHLD
import os
import sys
from rabbitmq_helpers import RabbitmqSelectLoopInteractor
from default_logger import logger

PROC_STR_ID_TO_CLASS_MAP = {
    'EpochCallbackManager': {
        'class': EpochCallbackManager,
        'name': 'PowerLoom|EpochCallbackManager',
        'target': None
    },
    'SystemEpochDetector': {
        'class': EpochDetectorProcess,
        'name': 'PowerLoom|SystemEpochDetector',
        'target': None
    }
}

with open('callback_modules/module_queues_config.json', 'r',encoding='utf-8') as f:
    contents = json.load(f)

CALLBACK_WORKERS_MAP = contents['callback_workers']


class ProcessHubCore(Process):
    def __init__(self, name, **kwargs):
        Process.__init__(self, name=name, **kwargs)
        self._spawned_processes_map: Dict[str, Union[Process, None]] = dict()
        self._spawned_cb_processes_map = dict()  # separate map for callback worker spawns
        self._thread_shutdown_event = threading.Event()
        self._shutdown_initiated = False

    def signal_handler(self, signum, frame):
        if signum == SIGCHLD and not self._shutdown_initiated:
            pid, status = os.waitpid(-1, os.WNOHANG | os.WUNTRACED | os.WCONTINUED)
            if os.WIFCONTINUED(status) or os.WIFSTOPPED(status):
                return
            if os.WIFSIGNALED(status) or os.WIFEXITED(status):
                self._logger.debug('Received process crash notification for child process PID: %s', pid)
                callback_worker_module_file = None
                callback_worker_class = None
                callback_worker_name = None
                callback_worker_unique_id = None
                for k, worker_unique_id_entries in self._spawned_cb_processes_map.items():
                    for unique_id, worker_process_details in worker_unique_id_entries.items():
                        if worker_process_details['process'].pid == pid:
                            self._logger.debug(
                                'Found crashed child process PID in spawned callback workers | '
                                'Callback worker class: %s | Unique worker identifier: %s',
                                k, worker_process_details['id']
                            )
                            callback_worker_class = k
                            callback_worker_name = worker_process_details['id']
                            callback_worker_unique_id = unique_id
                            for each_cb_worker_module_file, worker_type_list in CALLBACK_WORKERS_MAP.items():
                                self._logger.debug(
                                    'Searching callback workers specified in module %s for worker class %s details',
                                    each_cb_worker_module_file, callback_worker_class
                                )
                                if type(worker_type_list) is list:
                                    gen = (x for x in worker_type_list if x['class'] == callback_worker_class)
                                    worker_details = next(gen, None)
                                    if worker_details:
                                        callback_worker_module_file = each_cb_worker_module_file
                                        self._logger.debug(
                                            'Found callback worker process initiation name %s for worker class %s',
                                            callback_worker_name, callback_worker_class
                                        )
                                        break

                if callback_worker_module_file and callback_worker_class and callback_worker_name \
                        and callback_worker_unique_id:
                    worker_class = getattr(importlib.import_module(f'callback_modules.{callback_worker_module_file}'),
                                           callback_worker_class)
                    worker_obj: Process = worker_class(name=callback_worker_name)
                    worker_obj.start()
                    self._spawned_cb_processes_map[callback_worker_class][callback_worker_unique_id] = {
                        'id': callback_worker_name, 'process': worker_obj
                    }
                    self._logger.debug(
                        'Respawned callback worker class %s unique ID %s '
                        'with PID %s after receiving crash signal against PID %s',
                        callback_worker_class, callback_worker_unique_id, worker_obj.pid, pid
                    )
                    return

                for k, worker_unique_id in self._spawned_processes_map.items():
                    if worker_unique_id != -1 and worker_unique_id.pid == pid:
                        self._logger.debug('RESPAWNING: process for %s', k)
                        proc_details: dict = PROC_STR_ID_TO_CLASS_MAP.get(k)
                        init_kwargs = dict(name=proc_details['name'])
                        if proc_details.get('class'):
                            proc_obj = proc_details['class'](**init_kwargs)
                            proc_obj.start()
                        else:
                            proc_obj = Process(target=proc_details['target'])
                            proc_obj.start()
                        self._logger.debug('RESPAWNED: process for %s with PID: %s', k, proc_obj.pid)
                        self._spawned_processes_map[k] = proc_obj
        elif signum in [SIGINT, SIGTERM, SIGQUIT]:
            self._shutdown_initiated = True
            self.rabbitmq_interactor.stop()
            # raise GenericExitOnSignal

    def kill_process(self, pid: int):
        _logger = logging.getLogger(f'PowerLoom|ProcessHub|Core:{settings.NAMESPACE}-{settings.INSTANCE_ID}')
        p = psutil.Process(pid)
        _logger.debug('Attempting to send SIGTERM to process ID %s for following command', pid)
        p.terminate()
        _logger.debug('Waiting for 3 seconds to confirm termination of process')
        gone, alive = psutil.wait_procs([p], timeout=3)
        for p_ in alive:
            _logger.debug('Process ID %s not terminated by SIGTERM. Sending SIGKILL...', p_.pid)
            p_.kill()

        for k, v in self._spawned_cb_processes_map.items():
            if v['process'].pid == pid:
                v['process'].join()

        for k, v in self._spawned_processes_map.items():
            # internal state reporter might set proc_id_map[k] = -1
            if v != -1 and v.pid == pid:
                v.join()

    @provide_redis_conn
    def internal_state_reporter(self, redis_conn: redis.Redis = None):
        while not self._thread_shutdown_event.wait(timeout=2):
            proc_id_map = dict()
            for k, v in self._spawned_processes_map.items():
                if v:
                    proc_id_map[k] = v.pid
                else:
                    proc_id_map[k] = -1
            proc_id_map['callback_workers'] = dict()
            for k, unique_worker_entries in self._spawned_cb_processes_map.items():
                proc_id_map['callback_workers'][k] = dict()
                for worker_unique_id, worker_process_details in unique_worker_entries.items():
                    proc_id_map['callback_workers'][k][worker_unique_id] = {'pid': worker_process_details['process'].pid, 'id': worker_process_details['id']}
            proc_id_map['callback_workers'] = json.dumps(proc_id_map['callback_workers'])
            redis_conn.hset(name=f'powerloom:uniswap:{settings.NAMESPACE}:{settings.INSTANCE_ID}:Processes', mapping=proc_id_map)
        self._logger.error('Caught thread shutdown notification event. Deleting process worker map in redis...')
        redis_conn.delete(f'powerloom:uniswap:{settings.NAMESPACE}:{settings.INSTANCE_ID}:Processes')

    @cleanup_children_procs
    def run(self) -> None:
        setproctitle(f'PowerLoom|ProcessHub|Core')
        self._logger = logger.bind(module='PowerLoom|ProcessHub|Core')

        for signame in [SIGINT, SIGTERM, SIGQUIT, SIGCHLD]:
            signal(signame, self.signal_handler)

        for callback_worker_file, worker_list in CALLBACK_WORKERS_MAP.items():
            self._logger.debug('='*80)
            self._logger.debug('Launching workers for functionality %s', callback_worker_file)
            for each_worker in worker_list:
                # print(each_worker)
                worker_class = getattr(importlib.import_module(f'callback_modules.{callback_worker_file}'), each_worker['class'])
                worker_count = None

                # check if there is settings-config for workers
                if each_worker.get('class', '') == 'PairTotalReservesProcessor':
                    worker_count = settings.get('MODULE_QUEUES_CONFIG.PAIR_TOTAL_RESERVES.NUM_INSTANCES', None)

                # else if settings-config doesn't exist then use module_queues_config
                if not worker_count:
                    worker_count = each_worker.get('num_instances', 1)

                self._spawned_cb_processes_map[each_worker['class']] = dict()
                for _ in range(worker_count):
                    unique_id = str(uuid.uuid4())[:5]
                    unique_name = f'{each_worker["name"]}:{settings.NAMESPACE}:{settings.INSTANCE_ID}'+'-'+unique_id
                    worker_obj: Process = worker_class(name=unique_name)
                    worker_obj.start()
                    self._spawned_cb_processes_map[each_worker['class']].update({unique_id: {'id': unique_name, 'process': worker_obj}})
                    self._logger.debug(
                        'Process Hub Core launched process %s for callback worker %s with PID: %s',
                        unique_name, each_worker['class'], worker_obj.pid
                    )

                # self._spawned_processes_map[each_worker['name']] = worker_obj
            self._logger.debug('='*80)
        self._logger.debug('Starting Internal Process State reporter for Process Hub Core...')
        self._reporter_thread = Thread(target=self.internal_state_reporter)
        self._reporter_thread.start()
        self._logger.debug('Starting Process Hub Core...')

        queue_name = f"powerloom-processhub-commands-q:{settings.NAMESPACE}:{settings.INSTANCE_ID}"
        self.rabbitmq_interactor: RabbitmqSelectLoopInteractor = RabbitmqSelectLoopInteractor(
            consume_queue_name=queue_name,
            consume_callback=self.callback,
            consumer_worker_name=f'PowerLoom|ProcessHub|Core-{settings.INSTANCE_ID[:5]}'
        )
        self._logger.debug('Starting RabbitMQ consumer on queue %s', queue_name)
        self.rabbitmq_interactor.run()
        self._logger.debug('RabbitMQ interactor ioloop ended...')
        self._thread_shutdown_event.set()
        raise SelfExitException

    def callback(self, dont_use_ch, method, properties, body):
        self.rabbitmq_interactor._channel.basic_ack(delivery_tag=method.delivery_tag)
        command = json.loads(body)
        try:
            cmd_json = ProcessHubCommand(**command)
        except pydantic.ValidationError:
            self._logger.error('ProcessHubCore received unrecognized command')
            self._logger.error(command)
            return

        if cmd_json.command == 'stop':
            self._logger.debug('Process Hub Core received stop command: %s', cmd_json)
            process_id = cmd_json.pid
            proc_str_id = cmd_json.proc_str_id
            if process_id:
                return
            if proc_str_id:
                if proc_str_id == 'self':
                    return
                    # self._logger.error('Received stop command on self. Initiating shutdown...')
                    # raise SelfExitException
                mapped_p = self._spawned_processes_map.get(proc_str_id)
                if not mapped_p:
                    self._logger.error('Did not find process ID in core processes string map: %s', proc_str_id)
                    mapped_p = self._spawned_cb_processes_map.get(proc_str_id)
                    if not mapped_p:
                        self._logger.error('Did not find process ID in callback processes string map: %s', proc_str_id)
                        return
                    else:
                        self.kill_process(mapped_p.pid)
                        self._spawned_cb_processes_map[proc_str_id] = None
                else:
                    self.kill_process(mapped_p.pid)
                    self._spawned_processes_map[proc_str_id] = None

        elif cmd_json.command == 'start':
            try:
                self._logger.debug('Process Hub Core received start command: %s', cmd_json)
                proc_name = cmd_json.proc_str_id
                self._logger.debug('Process Hub Core launching process for %s', proc_name)
                proc_details: dict = PROC_STR_ID_TO_CLASS_MAP.get(proc_name)
                init_kwargs = dict(name=proc_details['name'])
                init_kwargs.update(cmd_json.init_kwargs)
                if proc_details.get('class'):
                    proc_obj = proc_details['class'](**init_kwargs)
                    proc_obj.start()
                else:
                    proc_obj = Process(target=proc_details['target'], kwargs=cmd_json.init_kwargs)
                    proc_obj.start()
                self._logger.debug('Process Hub Core launched process for %s with PID: %s', proc_name, proc_obj.pid)
                self._spawned_processes_map[proc_name] = proc_obj
            except Exception as err:
                self._logger.error(f"Error while starting a process:{cmd_json} | error_msg: {str(err)}", exc_info=True)
        elif cmd_json.command == 'restart':
            try:
                # TODO
                self._logger.debug('Process Hub Core received restart command: %s', cmd_json)
                proc_identifier = cmd_json.proc_str_id
                # first kill
                self._logger.debug('Attempting to kill process: %s', cmd_json.pid)
                self.kill_process(cmd_json.pid)
                self._logger.debug('Attempting to start process: %s', cmd_json.proc_str_id)
            except Exception as err:
                self._logger.error(f"Error while restarting a process:{cmd_json} | error_msg: {str(err)}", exc_info=True)


if __name__ == '__main__':
   
    p = ProcessHubCore(name='PowerLoom|UniswapPoolerProcessHub|Core')
    p.start()
    while p.is_alive():
        logger.debug('Process hub core is still alive. waiting on it to join...')
        try:
            p.join()
        except:
            pass

