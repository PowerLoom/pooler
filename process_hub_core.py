import threading

from exceptions import SelfExitException, GenericExitOnSignal
from redis_conn import provide_redis_conn
from threading import Thread
from multiprocessing import Process, log_to_stderr
from typing import Dict, Union
from init_rabbitmq import create_rabbitmq_conn
from dynaconf import settings
from message_models import ProcessHubCommand
from proto_system_logging import config_logger_with_namespace
from helper_functions import cleanup_children_procs
from system_ticker_linear import LinearTickerProcess
from system_epoch_collator import EpochCollatorProcess
from system_epoch_finalizer import EpochFinalizerProcess
from epoch_broadcast_callback_manager import EpochCallbackManager
import redis
import pydantic
import psutil
import logging
import logging.handlers
import importlib
import json
import time
from setproctitle import setproctitle
from signal import signal, pause, SIGINT, SIGTERM, SIGQUIT, SIGCHLD, SIG_DFL
import os
import sys
from rabbitmq_helpers import RabbitmqSelectLoopInteractor


PROC_STR_ID_TO_CLASS_MAP = {
    'SystemLinearEpochClock': {
        'class': LinearTickerProcess,
        'name': 'PowerLoom|SystemEpochClock|Linear',
        'target': None
    },
    'SystemEpochCollator': {
        'class': EpochCollatorProcess,
        'name': 'PowerLoom|SystemEpochCollator',
        'target': None
    },
    'SystemEpochFinalizer': {
        'class': EpochFinalizerProcess,
        'name': 'PowerLoom|SystemEpochFinalizer',
        'target': None
    },
    'EpochCallbackManager': {
        'class': EpochCallbackManager,
        'name': 'PowerLoom|EpochCallbackManager',
        'target': None
    },
    # 'SmartContractsEventsListener': {
    #     'name': 'PowerLoom|ContractEventsListener',
    #     'class': None,
    #     'target': contract_event_listener_main
    # }
}

with open('callback_modules/module_queues_config.json', 'r') as f:
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
                for k, v in self._spawned_cb_processes_map.items():
                    if v['process'].pid == pid:
                        self._logger.debug(
                            'Found crashed child process PID in spawned callback workers | Callback worker class: %s ',
                            k
                        )
                        callback_worker_class = k
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
                                    callback_worker_name = worker_details['name']
                                    self._logger.debug(
                                        'Found callback worker process initiation name %s for worker class %s',
                                        callback_worker_name, callback_worker_class
                                    )
                                    break

                if callback_worker_module_file and callback_worker_class and callback_worker_name:
                    worker_class = getattr(importlib.import_module(f'callback_modules.{callback_worker_module_file}'),
                                           callback_worker_class)
                    worker_obj: Process = worker_class(name=callback_worker_name)
                    worker_obj.start()
                    self._spawned_cb_processes_map[callback_worker_class] = {
                        'id': worker_obj.name, 'process': worker_obj
                    }
                    self._logger.debug(
                        'Respawned callback worker class %s with PID %s after receiving crash signal against PID %s',
                        callback_worker_class, worker_obj.pid, pid
                    )
                    return
                        
                for k, v in self._spawned_processes_map.items():
                    if v != -1 and v.pid == pid:
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
        _logger = logging.getLogger('PowerLoom|ProcessHub|Core')
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
            for k, v in self._spawned_cb_processes_map.items():
                if v:
                    proc_id_map['callback_workers'][k] = {'pid': v['process'].pid, 'id': v['id']}
            proc_id_map['callback_workers'] = json.dumps(proc_id_map['callback_workers'])
            redis_conn.hmset(f'powerloom:uniswap:{settings.NAMESPACE}:Processes', proc_id_map)
        self._logger.error('Caught thread shutdown notification event. Deleting process worker map in redis...')
        redis_conn.delete(f'powerloom:uniswap:{settings.NAMESPACE}:Processes')

    @cleanup_children_procs
    def run(self) -> None:
        # self._logger = get_mp_logger()
        # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|ProcessHub|Core'))
        setproctitle(f'PowerLoom|ProcessHub|Core')
        self._logger = logging.getLogger('PowerLoom|ProcessHub|Core') 
        self._logger.setLevel(logging.DEBUG)
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(logging.DEBUG)
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.ERROR)
        self._logger.handlers = [
            logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT),
            stdout_handler, stderr_handler
        ]
        
        for signame in [SIGINT, SIGTERM, SIGQUIT, SIGCHLD]:
            signal(signame, self.signal_handler)

        for callback_worker_file, worker_list in CALLBACK_WORKERS_MAP.items():
            self._logger.debug('='*80)
            self._logger.debug('Launching workers for functionality %s', callback_worker_file)
            for each_worker in worker_list:
                print(each_worker)
                worker_class = getattr(importlib.import_module(f'callback_modules.{callback_worker_file}'), each_worker['class'])
                worker_obj: Process = worker_class(name=each_worker['name'])
                worker_obj.start()
                self._spawned_cb_processes_map[each_worker['class']] = {'id': worker_obj.name, 'process': worker_obj}
                # self._spawned_processes_map[each_worker['name']] = worker_obj
                self._logger.debug('Process Hub Core launched process for callback worker %s with PID: %s', each_worker['class'], worker_obj.pid)
            self._logger.debug('='*80)
        self._logger.debug('Starting Internal Process State reporter for Process Hub Core...')
        self._reporter_thread = Thread(target=self.internal_state_reporter)
        self._reporter_thread.start()
        self._logger.debug('Starting Process Hub Core...')

        queue_name = f"powerloom-processhub-commands-q:{settings.NAMESPACE}"
        self.rabbitmq_interactor: RabbitmqSelectLoopInteractor = RabbitmqSelectLoopInteractor(
            consume_queue_name=queue_name,
            consume_callback=self.callback,
            consumer_worker_name='PowerLoom|ProcessHub|Core'
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
    logger = logging.getLogger('PowerLoom|ProcessHub|Core')
    logger.setLevel(logging.DEBUG)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    logger.handlers = [
        logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT),
        stdout_handler, stderr_handler
    ]

    p = ProcessHubCore(name='PowerLoom|UniswapPoolerProcessHub|Core')
    p.start()
    while p.is_alive():
        logger.debug('Process hub core is still alive. waiting on it to join...')
        try:
            p.join()
        except:
            pass

