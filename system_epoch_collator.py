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
import uuid
import logging
import time
import tooz
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
    setproctitle(f'PowerLoom|EpochCollator')
    member_id = f'powerloom:epoch:collator:{settings.NAMESPACE}'
    coordinator = coordination.get_coordinator(f'kazoo://{construct_kazoo_url()}', member_id)
    coordinator.start(start_heart=True)
    group_id = f'powerloom:epoch:reports:{settings.NAMESPACE}'
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
            t_logger.debug('Worker %s will attempt to REJOIN group %s. Delaying '
                          'for earlier dead worker to be removed from tooz group | Retry %d', member_id,
                          group_id, c)
            c += 1
            time.sleep(2)
        else:
            break
    else:
        raise Exception('tooz group joining failed for member %s on group %s', member_id, group_id)
    t_logger.debug('Joined Tooz group %s', group_id)
    try:
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
    except:
        try:
            coordinator.leave_group(group_id).get()
        except:
            pass


class EpochCollatorProcess(Process):
    def __init__(self, name, **kwargs):
        Process.__init__(self, name=name, **kwargs)
        self._last_reorg = dict(begin=0, end=0)
        self._queued_linear_epochs = list()

    def _epoch_collator(self, ch, method, properties, body):
        try:
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
        except Exception as err:
            self._logger.error(f"Error while passing acknowledgement in EpochCollator error_msg:{str(err)}", exc_info=True)

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
                ch.close()
                c.close()
            except:
                pass
            try:
                self._tooz_reporter.join(timeout=5)
            except:
                pass