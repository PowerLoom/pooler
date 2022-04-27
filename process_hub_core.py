from exceptions import SelfExitException
from redis_conn import provide_redis_conn
from threading import Thread
from multiprocessing import Process, log_to_stderr
from typing import Dict, Union
from init_rabbitmq import create_rabbitmq_conn
from dynaconf import settings
from message_models import ProcessHubCommand
from proto_system_logging import config_logger_with_namespace
from callback_modules.gunicorn_contract_event_listener import main as contract_event_listener_main
from process_marketmaker_contracts import main as marketmaker_processor_main
from helper_functions import cleanup_children_procs
from system_ticker_linear import main_ticker_process as linear_epoch_ticker
from system_epoch_collator import EpochCollatorProcess
from system_epoch_finalizer import main as epoch_finalizer_main
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
        'class': None,
        'name': 'PowerLoom|SystemEpochClock|Linear',
        'target': linear_epoch_ticker
    },
    'SystemEpochCollator': {
        'class': EpochCollatorProcess,
        'name': 'PowerLoom|SystemEpochCollator',
        'target': None
    },
    'SystemEpochFinalizer': {
        'class': None,
        'name': 'PowerLoom|SystemEpochFinalizer',
        'target': epoch_finalizer_main
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

    def signal_handler(self, signum, frame):
        if signum == SIGCHLD:
            pid, status = os.waitpid(-1, os.WNOHANG|os.WUNTRACED|os.WCONTINUED)
            if os.WIFCONTINUED(status) or os.WIFSTOPPED(status):
                return
            if os.WIFSIGNALED(status) or os.WIFEXITED(status):
                for k, v in self._spawned_cb_processes_map.items():
                    if v['process'].pid == pid:
                        v['process'].start()
                for k, v in self._spawned_processes_map.items():
                    if v != -1 and v.pid == pid:
                        v.start()
        else:

            print(f"signal_handler is running with PID:{os.getpid()}")

            # mother shouldn't be notified when it terminates children
            signal(SIGCHLD, SIG_DFL)
            for k, v in self._spawned_cb_processes_map.items():
                if v['process'].is_alive():
                    v['process'].terminate()
                    v['process'].join()
            for k, v in self._spawned_processes_map.items():
                if v != -1 and v.is_alive():
                    v.terminate()
                    v.join()

            sys.exit(0)

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
        if hasattr(self, '_spawned_cb_processes_map'):
            for k, v in self._spawned_cb_processes_map.items():
                if v['process'].pid == pid:
                    v['process'].join()
        if hasattr(self, '_spawned_processes_map'):
            for k, v in self._spawned_processes_map.items():
                # internal state reporter might set proc_id_map[k] = -1 
                if v != -1 and v.pid == pid:
                    v.join()

    @provide_redis_conn
    def internal_state_reporter(self, redis_conn: redis.Redis = None):
        _logger = logging.getLogger('PowerLoom|ProcessHub|Core')
        try:
            while True:
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
                time.sleep(2)
        except SelfExitException:
            redis_conn.delete(f'powerloom:uniswap:{settings.NAMESPACE}:Processes')
        except Exception as err:
            # KeyboardInterrupt can be raised and should be ignored
            _logger.error(f"Error in internal state reporter: {str(err)}", exc_info=True)
            

    @cleanup_children_procs
    def run(self) -> None:
        # self._logger = get_mp_logger()
        # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|ProcessHub|Core'))
        setproctitle(f'PowerLoom|ProcessHub|Core')
        self._logger = logging.getLogger('PowerLoom|ProcessHub|Core') 
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers = [logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]
        
        for signame in [SIGINT, SIGTERM, SIGQUIT, SIGCHLD]:
            signal(signame, self.signal_handler)

        for callback_worker_file, worker_list in CALLBACK_WORKERS_MAP.items():
            self._logger.debug('='*80)
            self._logger.debug('Launching workers for functionality %s', callback_worker_file)
            for each_worker in worker_list:
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
            consume_callback=self.callback
        )
        self._logger.debug('Starting RabbitMQ consumer on queue %s', queue_name)
        self.rabbitmq_interactor.run()

    def callback(self, ch, method, properties, body):
        ch.basic_ack(delivery_tag=method.delivery_tag)
        command = json.loads(body)
        try:
            cmd_json = ProcessHubCommand(**command)
        except pydantic.ValidationError:
            self._logger.error('ProcessHubCore received unrecognized command')
            self._logger.error(command)
            return
        
        if cmd_json.command == 'stop':
            try:
                self._logger.debug('Process Hub Core received stop command: %s', cmd_json)
                process_id = cmd_json.pid
                proc_str_id = cmd_json.proc_str_id
                if process_id:
                    self.kill_process(process_id)
                if proc_str_id:
                    if proc_str_id == 'self':
                        self._logger.error('Received stop command on self. Initiating shutdown...')
                        raise SelfExitException
                    mapped_p = self._spawned_processes_map.get(proc_str_id)
                    if not mapped_p:
                        self._logger.error('Did not find process ID in local process string map: %s', proc_str_id)
                        return
                    else:
                        self.kill_process(mapped_p.pid)
                        self._spawned_processes_map[proc_str_id] = None
            except Exception as err:
                self._logger.error(f"Error while killing/stopping a process:{cmd_json} | error_msg: {str(err)}", exc_info=True)
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
