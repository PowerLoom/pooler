from signal import SIGINT, SIGTERM, SIGQUIT, signal
from message_models import EpochConsensusReport, EpochBroadcast, SystemEpochStatusReport
from exceptions import GenericExitOnSignal, SelfExitException
from dynaconf import settings
from helper_functions import construct_kazoo_url
from multiprocessing import Process
from tooz import coordination
from functools import wraps
from setproctitle import setproctitle
from threading import Thread
from uuid import uuid4
from rabbitmq_helpers import RabbitmqSelectLoopInteractor
import threading
import queue
import sys
import uuid
import logging
import time
import tooz
import logging.handlers
import json


def collate_epoch(
        consensus_report: EpochConsensusReport,
) -> SystemEpochStatusReport:
    broadcast_id = str(uuid4())
    broadcast_msg = SystemEpochStatusReport(
        begin=consensus_report.begin,
        end=consensus_report.end,
        broadcast_id=broadcast_id,
        reorg=consensus_report.reorg
    )
    return broadcast_msg


def rabbitmq_tooz_cleanup(fn):
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            fn(self, *args, **kwargs)
        except (GenericExitOnSignal, KeyboardInterrupt):
            try:
                #self._logger.debug('Waiting for RabbitMQ interactor ioloop to stop...')
                #self._rabbitmq_interactor.stop()
                self._logger.debug('Waiting for tooz reporter thread to join...')
                self._tooz_reporter.join()
                self._logger.debug('Tooz reporter thread joined...')
            except:
                pass
        finally:
            sys.exit(0)
    return wrapper


class EpochCollatorProcess(Process):
    def __init__(self, name, **kwargs):
        Process.__init__(self, name=name, **kwargs)
        self._last_reorg = dict(begin=0, end=0)
        self._queued_linear_epochs = list()
        self._rabbitmq_interactor = None
        self._shutdown_initiated = False
        self._reporter_thread_shutdown_event = threading.Event()
        self._state_update_q = queue.Queue()

    def _exit_signal_handler(self, signum, sigframe):
        self._logger.debug('Received signal %s', signum)
        if signum in [SIGINT, SIGTERM, SIGQUIT] and not self._shutdown_initiated:
            self._shutdown_initiated = True
            self._rabbitmq_interactor.stop()

    def state_report_thread(self):
        member_id = f'powerloom:epoch:collator:{settings.NAMESPACE}:{settings.INSTANCE_ID}'
        coordinator = coordination.get_coordinator(f'kazoo://{construct_kazoo_url()}', member_id)
        coordinator.start(start_heart=True)
        group_id = f'powerloom:epoch:reports:{settings.NAMESPACE}:{settings.INSTANCE_ID}'
        group_id = group_id.encode('utf-8')
        try:
            coordinator.create_group(group_id).get()
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
                coordinator.join_group(group_id, capabilities=init_state_capabilities).get()
            except tooz.coordination.MemberAlreadyExist:
                self._logger.debug('Worker %s will attempt to REJOIN group %s. Delaying '
                               'for earlier dead worker to be removed from tooz group | Retry %d', member_id,
                               group_id, c)
                c += 1
                time.sleep(2)
            else:
                break
        else:
            raise Exception('tooz group joining failed for member %s on group %s', member_id, group_id)
        self._logger.debug('Joined Tooz group %s', group_id)
        self._logger.debug('Waiting for processed epoch consensus reports...')
        while not self._reporter_thread_shutdown_event.wait(timeout=2):
            try:
                latest_state = self._state_update_q.get_nowait()
            except:
                continue
            self._logger.debug('Got processed epoch update')
            self._logger.debug(latest_state)
            coordinator.update_capabilities(
                group_id,
                capabilities=latest_state.dict()
            ).get()
            self._logger.debug('Reported latest epoch collation state to tooz: %s', latest_state)
            self._state_update_q.task_done()
        self._logger.info('Tooz reporter thread received shut down event...')
        try:
            coordinator.leave_group(group_id).get()
            coordinator.stop()
        except:
            pass

    def _epoch_collator(self, do_not_use_ch, method, properties, body):
        try:
            self._rabbitmq_interactor._channel.basic_ack(delivery_tag=method.delivery_tag)
            self._logger.debug('Received epoch consensus report')
            cmd = json.loads(body)
            self._logger.debug(cmd)
            consensus_report = EpochConsensusReport(**cmd)
            if consensus_report.reorg:
                self._last_reorg['begin'] = consensus_report.begin
                self._last_reorg['end'] = consensus_report.end
                broadcast = collate_epoch(consensus_report)
                broadcast = broadcast.dict()
                broadcast.update({'reorg': True})
                self._state_update_q.put(broadcast)
            else:
                broadcast = collate_epoch(consensus_report)
                self._state_update_q.put(broadcast)
        except Exception as err:
            self._logger.error(f"Error while passing acknowledgement in EpochCollator error_msg:{str(err)}", exc_info=True)

    @rabbitmq_tooz_cleanup
    def run(self):
        # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|EpochCollator'))
        setproctitle(f'PowerLoom|EpochCollator')
        for signame in [SIGINT, SIGTERM, SIGQUIT]:
            signal(signame, self._exit_signal_handler)
        self._logger = logging.getLogger('PowerLoom|EpochCollator')
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers = [
            logging.handlers.SocketHandler(host=settings.get('LOGGING_SERVER.HOST','localhost'),
            port=settings.get('LOGGING_SERVER.PORT',logging.handlers.DEFAULT_TCP_LOGGING_PORT))
        ]
        self._tooz_reporter = Thread(target=self.state_report_thread)
        self._tooz_reporter.start()
        self._logger.debug('Started Epoch Collator tooz reporter thread')

        queue_name = f"powerloom-epoch-consensus-q:{settings.NAMESPACE}:{settings.INSTANCE_ID}"
        self._rabbitmq_interactor: RabbitmqSelectLoopInteractor = RabbitmqSelectLoopInteractor(
            consume_queue_name=queue_name,
            consume_callback=self._epoch_collator,
            consumer_worker_name='PowerLoom|EpochCollator'
        )
        # self.rabbitmq_interactor.start_publishing()
        self._logger.debug('Starting RabbitMQ consumer on queue %s', queue_name)
        self._rabbitmq_interactor.run()
        self._logger.debug('%s: RabbitMQ interactor ioloop ended...', self.name)
        self._reporter_thread_shutdown_event.set()
        raise GenericExitOnSignal
