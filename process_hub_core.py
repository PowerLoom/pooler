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
    'LiquidityCacher': None,
    'SnapshotBuilder': None,
    'SmartContractsEventsListener': {
        'name': 'PowerLoom|ContractEventsListener',
        'class': None,
        'target': contract_event_listener_main
    },
    'MarketMakerContractsProcessor': {
        'name': 'PowerLoom|MarketMakerProcessor|Main',
        'class': None,
        'target': marketmaker_processor_main
    }
}

with open('callback_modules/module_queues_config.json', 'r') as f:
    contents = json.load(f)

CALLBACK_WORKERS_MAP = contents['callback_workers']


def kill_process(pid: int):
    _logger = logging.getLogger('PowerLoom|ProcessHub|Core')
    p = psutil.Process(pid)
    _logger.debug('Attempting to send SIGTERM to process ID %s for following command', pid)
    p.terminate()
    _logger.debug('Waiting for 3 seconds to confirm termination of process')
    gone, alive = psutil.wait_procs([p], timeout=3)
    for p_ in alive:
        _logger.debug('Process ID %s not terminated by SIGTERM. Sending SIGKILL...', p_.pid)
        p_.kill()


class ProcessHubCore(Process):
    def __init__(self, name, **kwargs):
        Process.__init__(self, name=name, **kwargs)
        self._spawned_processes_map: Dict[str, Union[Process, None]] = dict()

    @provide_redis_conn
    def internal_state_reporter(self, redis_conn: redis.Redis = None):
        try:
            while True:
                proc_id_map = dict()
                for k, v in self._spawned_processes_map.items():
                    if v:
                        proc_id_map[k] = v.pid
                    else:
                        proc_id_map[k] = -1
                redis_conn.hmset(f'powerloom:polymarket:{settings.NAMESPACE}:Processes', proc_id_map)
                time.sleep(2)
        except KeyboardInterrupt:
            redis_conn.delete(f'powerloom:polymarket:{settings.NAMESPACE}:Processes')

    @cleanup_children_procs
    def run(self) -> None:
        # self._logger = get_mp_logger()
        # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|ProcessHub|Core'))
        self._logger = logging.getLogger('PowerLoom|ProcessHub|Core')
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers = [logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]
        for callback_worker_file, worker_list in CALLBACK_WORKERS_MAP.items():
            self._logger.debug('='*80)
            self._logger.debug('Launching workers for functionality %s', callback_worker_file)
            for each_worker in worker_list:
                worker_class = getattr(importlib.import_module(f'callback_modules.{callback_worker_file}'), each_worker['class'])
                worker_obj = worker_class(name=each_worker['name'])
                worker_obj.start()
                self._spawned_processes_map[each_worker['class']] = worker_obj
                self._logger.debug('Process Hub Core launched process for callback worker %s with PID: %s', each_worker['class'], worker_obj.pid)
            self._logger.debug('='*80)
        self._logger.debug('Starting Internal Process State reporter for Process Hub Core...')
        self._reporter_thread = Thread(target=self.internal_state_reporter)
        self._reporter_thread.start()
        self._logger.debug('Starting Process Hub Core...')
        connection = create_rabbitmq_conn()
        channel = connection.channel()
        queue_name = f"powerloom-processhub-commands-q:{settings.NAMESPACE}"
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(
            queue=queue_name,
            on_message_callback=self.callback,
            auto_ack=False
        )
        channel.start_consuming()

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
            self._logger.debug('Process Hub Core received stop command: %s', cmd_json)
            process_id = cmd_json.pid
            proc_str_id = cmd_json.proc_str_id
            if process_id:
                kill_process(process_id)
            if proc_str_id:
                if proc_str_id == 'self':
                    self._logger.error('Received stop command on self. Initiating shutdown...')
                    raise SelfExitException
                mapped_p = self._spawned_processes_map.get(proc_str_id)
                if not mapped_p:
                    self._logger.error('Did not find process ID in local process string map: %s', proc_str_id)
                    return
                else:
                    kill_process(mapped_p.pid)
                    self._spawned_processes_map[proc_str_id] = None
        elif cmd_json.command == 'start':
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
                proc_obj = Process(target=proc_details['target'], **init_kwargs)
                proc_obj.start()
            self._logger.debug('Process Hub Core launched process for %s with PID: %s', proc_name, proc_obj.pid)
            self._spawned_processes_map[proc_name] = proc_obj
        elif cmd_json.command == 'restart':
            # TODO
            self._logger.debug('Process Hub Core received restart command: %s', cmd_json)
            proc_identifier = cmd_json.proc_str_id
            # first kill
            self._logger.debug('Attempting to kill process: %s', cmd_json.pid)
            kill_process(cmd_json.pid)
            self._logger.debug('Attempting to start process: %s', cmd_json.proc_str_id)
