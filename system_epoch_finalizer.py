from signal import SIGINT, SIGTERM, SIGQUIT, signal
from exceptions import GenericExitOnSignal
from message_models import EpochConsensusReport, EpochBroadcast, SystemEpochStatusReport
from functools import wraps
from dynaconf import settings
from time import sleep
from tooz import coordination
from helper_functions import construct_kazoo_url
from pydantic import ValidationError as PydanticValidationError
from setproctitle import setproctitle
from rabbitmq_helpers import RabbitmqThreadedSelectLoopInteractor
import sys
import signal
import threading
import logging.handlers
import queue
import tooz
import time
import multiprocessing

# logging.config.dictConfig(config_logger_with_namespace('PowerLoom|EpochFinalizer'))
finalizer_logger = logging.getLogger('PowerLoom|EpochFinalizer')
finalizer_logger.setLevel(logging.DEBUG)
finalizer_logger.handlers = [logging.handlers.SocketHandler(host=settings.get('LOGGING_SERVER.HOST','localhost'),
            port=settings.get('LOGGING_SERVER.PORT',logging.handlers.DEFAULT_TCP_LOGGING_PORT))]


def rabbitmq_tooz_cleanup(fn):
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            fn(self, *args, **kwargs)
        except (GenericExitOnSignal, KeyboardInterrupt):
            try:
                self._logger.debug('Waiting for RabbitMQ interactor thread to join...')
                self._rabbitmq_thread.join()
                self._logger.debug('RabbitMQ interactor thread joined. Waiting to leave tooz group...')
                self._tooz_coordinator.leave_group(self._group_id).get()
                self._logger.debug('Left Tooz group. Waiting to stop tooz coordinator object...')
                self._tooz_coordinator.stop()
            except:
                pass
        finally:
            sys.exit(0)
    return wrapper


class EpochFinalizerProcess(multiprocessing.Process):
    def __init__(self, name, **kwargs):
        multiprocessing.Process.__init__(self, name=name, **kwargs)
        self._rabbitmq_thread: threading.Thread
        self._rabbitmq_queue = queue.Queue()
        self._tooz_coordinator = None
        self._shutdown_initiated = False
        self._group_id = f'powerloom:epoch:reports:{settings.NAMESPACE}:{settings.INSTANCE_ID}'.encode('utf-8')  # tooz group ID

    def _interactor_wrapper(self, q: queue.Queue):  # run in a separate thread
        self._rabbitmq_interactor = RabbitmqThreadedSelectLoopInteractor(
            publish_queue=q, consumer_worker_name=self.name
        )
        self._rabbitmq_interactor.run()  # blocking

    def _generic_exit_handler(self, signum, sigframe):
        if signum in [SIGINT, SIGTERM, SIGQUIT] and not self._shutdown_initiated:
            self._shutdown_initiated = True
            self._rabbitmq_interactor.stop()
            raise GenericExitOnSignal

    @rabbitmq_tooz_cleanup
    def run(self):
        # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|EpochCollator'))
        for signame in [signal.SIGINT, signal.SIGTERM, signal.SIGQUIT]:
            signal.signal(signame, self._generic_exit_handler)
        exchange = f'{settings.RABBITMQ.SETUP.CORE.EXCHANGE}:{settings.NAMESPACE}'
        routing_key = f'epoch-broadcast:{settings.NAMESPACE}:{settings.INSTANCE_ID}'
        self._rabbitmq_thread = threading.Thread(target=self._interactor_wrapper, kwargs={'q': self._rabbitmq_queue})
        self._rabbitmq_thread.start()

        self._logger = logging.getLogger(f'PowerLoom|EpochFinalizer|{settings.NAMESPACE}-{settings.INSTANCE_ID[:5]}')
        self._logger.setLevel(logging.DEBUG)
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(logging.DEBUG)
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.ERROR)
        self._logger.handlers = [
            logging.handlers.SocketHandler(host=settings.get('LOGGING_SERVER.HOST','localhost'),
            port=settings.get('LOGGING_SERVER.PORT',logging.handlers.DEFAULT_TCP_LOGGING_PORT)),
            stdout_handler, stderr_handler
        ]
        setproctitle(f'PowerLoom|EpochFinalizer')
        member_id = f'powerloom:epoch:finalizer:{settings.NAMESPACE}:{settings.INSTANCE_ID}'
        self._tooz_coordinator = coordination.get_coordinator(f'kazoo://{construct_kazoo_url()}', member_id)
        self._tooz_coordinator.start(start_heart=True)
        last_reorg_state = SystemEpochStatusReport(begin=0, end=0, reorg=False, broadcast_id='dummy')
        last_epoch_broadcast = EpochBroadcast(begin=0, end=0, broadcast_id='dummy')
        try:
            self._tooz_coordinator.create_group(self._group_id).get()
        except coordination.GroupAlreadyExist:
            pass
        init_state_capabilities = {
            'broadcast_id': 'NoBroadcast',
            'begin': 0,
            'end': 0,
            'reorg': False
        }
        c = 0
        while c < 10:
            try:
                self._tooz_coordinator.join_group(self._group_id, capabilities=init_state_capabilities).get()
            except tooz.coordination.MemberAlreadyExist:
                finalizer_logger.debug('Worker %s will attempt to REJOIN group %s. Delaying '
                                       'for earlier dead worker to be removed from tooz group | Retry %d', member_id,
                                       self._group_id, c)
                c += 1
                # coordinator.leave_group(group_id).get()
                time.sleep(2)
            else:
                break
        else:
            raise Exception('tooz group joining failed for member %s on group %s', member_id, self._group_id)
        while True:
            get_capabilities = [(member, self._tooz_coordinator.get_member_capabilities(self._group_id, member))
                                for member in self._tooz_coordinator.get_members(self._group_id).get()]

            for member, cap in get_capabilities:
                # print("Member %s has capabilities: %s" % (member, cap.get()))
                member_name = member.decode('utf-8') if type(member) == bytes else member
                if member_name == f'powerloom:epoch:collator:{settings.NAMESPACE}:{settings.INSTANCE_ID}':
                    report = cap.get()
                    try:
                        report_obj = SystemEpochStatusReport(**report)
                    except PydanticValidationError:
                        continue
                    # finalizer_logger.debug("Finalized epoch at: %s", report_obj)
                    if report_obj.reorg:
                        last_reorg_state = report_obj
                    else:
                        if not last_reorg_state.broadcast_id == 'dummy':
                            if report_obj.begin <= last_reorg_state.begin:
                                if report_obj.end <= last_reorg_state.end:
                                    pass  # dont broadcast
                            #  TODO: Handle cases around new linear epoch messages and last known reorg state
                        else:
                            if report_obj.begin > last_epoch_broadcast.end:
                                finalizer_logger.info('Broadcasting finalized epoch for callbacks: %s', report_obj)
                                brodcast_msg = (report_obj.json().encode('utf-8'), exchange, routing_key)
                                self._rabbitmq_queue.put(brodcast_msg)
                                finalizer_logger.info('DONE: Broadcasting finalized epoch for callbacks: %s',
                                                      report_obj)
                                last_epoch_broadcast = EpochBroadcast(begin=report_obj.begin, end=report_obj.end,
                                                                      broadcast_id=report_obj.broadcast_id)
            sleep(1)

