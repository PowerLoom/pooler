from proto_system_logging import config_logger_with_namespace
from message_models import EpochConsensusReport, EpochBroadcast, SystemEpochStatusReport
from init_rabbitmq import create_rabbitmq_conn
from dynaconf import settings
from helper_functions import construct_kazoo_url
from multiprocessing import Process
from tooz import coordination
from setproctitle import setproctitle
from threading import Thread
from queue import Queue
from uuid import uuid4
from pydantic import ValidationError as PydanticValidationError
import logging
import logging.handlers
import json
import pika

state_update_q = Queue()


def collate_epoch(
        ch: pika.adapters.blocking_connection.BlockingChannel,
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


def state_report_thread():
    t_logger = logging.getLogger('PowerLoom|EpochCollator')
    # t_logger.handlers = [logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]
    coordinator = coordination.get_coordinator(f'kazoo://{construct_kazoo_url()}', 'powerloom:epoch:collator')
    coordinator.start(start_heart=True)
    group_id = 'powerloom:epoch:reports'
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
    coordinator.join_group(group_id, capabilities=init_state_capabilities).get()
    t_logger.debug('Joined Tooz group %s', group_id)
    while True:
        t_logger.debug('Waiting for processed epoch consensus reports...')
        latest_state = state_update_q.get(block=True)
        t_logger.debug('Got processed epoch update')
        t_logger.debug(latest_state)
        coordinator.update_capabilities(
            group_id,
            capabilities=latest_state.dict()
        ).get()
        t_logger.debug('Reported latest epoch collation state to tooz: %s', latest_state)
        state_update_q.task_done()


class EpochCollatorProcess(Process):
    def __init__(self, name, **kwargs):
        Process.__init__(self, name=name, **kwargs)
        self._last_reorg = dict(begin=0, end=0)
        self._queued_linear_epochs = list()

    def _epoch_collator(self, ch, method, properties, body):
        ch.basic_ack(delivery_tag=method.delivery_tag)
        self._logger.debug('Received epoch consensus report')
        cmd = json.loads(body)
        self._logger.debug(cmd)
        consensus_report = EpochConsensusReport(**cmd)
        if consensus_report.reorg:
            self._last_reorg['begin'] = consensus_report.begin
            self._last_reorg['end'] = consensus_report.end
            broadcast = collate_epoch(ch, consensus_report)
            broadcast = broadcast.dict()
            broadcast.update({'reorg': True})
            state_update_q.put(broadcast)
        else:
            broadcast = collate_epoch(ch, consensus_report)
            state_update_q.put(broadcast)

    def run(self) -> None:
        # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|EpochCollator'))
        self._logger = logging.getLogger('PowerLoom|EpochCollator')
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers = [logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]
        self._tooz_reporter = Thread(target=state_report_thread)
        self._tooz_reporter.start()
        self._logger.debug('Started Epoch Collator tooz reporter thread')
        c = create_rabbitmq_conn()
        ch = c.channel()

        queue_name = f"powerloom-epoch-consensus-q:{settings.NAMESPACE}"
        ch.basic_qos(prefetch_count=1)
        ch.basic_consume(
            queue=queue_name,
            on_message_callback=self._epoch_collator,
            auto_ack=False
        )
        try:
            self._logger.debug('Starting RabbitMQ consumer on queue %s', queue_name)
            ch.start_consuming()
        except:
            pass
        finally:
            try:
                self._tooz_reporter.join()
            except:
                pass
            try:
                ch.close()
                c.close()
            except:
                pass
            try:
                self._tooz_reporter.join(timeout=5)
            except:
                pass