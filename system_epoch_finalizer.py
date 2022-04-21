from proto_system_logging import config_logger_with_namespace
from message_models import EpochConsensusReport, EpochBroadcast, SystemEpochStatusReport
from init_rabbitmq import create_rabbitmq_conn
from dynaconf import settings
from time import sleep
from tooz import coordination
from helper_functions import construct_kazoo_url
from pydantic import ValidationError as PydanticValidationError
from rabbitmq_helpers import RabbitmqThreadedSelectLoopInteractor
import threading
import logging.handlers
import queue
import tooz
import time
import pika
from setproctitle import setproctitle

# logging.config.dictConfig(config_logger_with_namespace('PowerLoom|EpochFinalizer'))
finalizer_logger = logging.getLogger('PowerLoom|EpochFinalizer')
finalizer_logger.setLevel(logging.DEBUG)
finalizer_logger.handlers = [logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]


# TODO: Handle delivery failures
def broadcast_epoch(
        ch: pika.adapters.blocking_connection.BlockingChannel,
        epoch_report: SystemEpochStatusReport,
) -> EpochBroadcast:
    report = SystemEpochStatusReport(begin=epoch_report.begin, end=epoch_report.end,
                                     broadcast_id=epoch_report.broadcast_id)
    broadcast_msg = report
    ch.basic_publish(
        exchange=f'{settings.RABBITMQ.SETUP.CORE.EXCHANGE}:{settings.NAMESPACE}',
        routing_key=f'epoch-broadcast:{settings.NAMESPACE}',
        body=broadcast_msg.json().encode('utf-8'),
        properties=pika.BasicProperties(
            delivery_mode=2,
            content_type='text/plain',
            content_encoding='utf-8'
        ),
        mandatory=True
    )
    return broadcast_msg


def interactor_wrapper_obj(q: queue.Queue):
    s = RabbitmqThreadedSelectLoopInteractor(publish_queue=q)
    s.run()


def main():
    exchange = f'{settings.RABBITMQ.SETUP.CORE.EXCHANGE}:{settings.NAMESPACE}'
    routing_key = f'epoch-broadcast:{settings.NAMESPACE}'

    q = queue.Queue()
    t = threading.Thread(target=interactor_wrapper_obj, kwargs={'q': q})
    t.start()

    last_reorg_state = SystemEpochStatusReport(begin=0, end=0, reorg=False, broadcast_id='dummy')
    last_epoch_broadcast = EpochBroadcast(begin=0, end=0, broadcast_id='dummy')
    setproctitle(f'PowerLoom|SystemEpochFinalizer')
    member_id = f'powerloom:epoch:finalizer:{settings.NAMESPACE}'
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
            finalizer_logger.debug('Worker %s will attempt to REJOIN group %s. Delaying '
                          'for earlier dead worker to be removed from tooz group | Retry %d', member_id,
                          group_id, c)
            c += 1
            # coordinator.leave_group(group_id).get()
            time.sleep(2)
        else:
            break
    else:
        raise Exception('tooz group joining failed for member %s on group %s', member_id, group_id)
    try:
        while True:
            get_capabilities = [(member, coordinator.get_member_capabilities(group_id, member))
                                for member in coordinator.get_members(group_id).get()]

            for member, cap in get_capabilities:
                # print("Member %s has capabilities: %s" % (member, cap.get()))
                member_name = member.decode('utf-8') if type(member) == bytes else member
                if 'powerloom:epoch:collator' in member_name and settings.NAMESPACE in member_name:
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
                                q.put(brodcast_msg)
                                finalizer_logger.info('DONE: Broadcasting finalized epoch for callbacks: %s', report_obj)
                                last_epoch_broadcast = EpochBroadcast(begin=report_obj.begin, end=report_obj.end, broadcast_id=report_obj.broadcast_id)
                            # else:
                            #     finalizer_logger.debug('Skipping status report from collator for a final broadcast: %s', report_obj)
            sleep(1)
    except:
        pass
    finally:
        try:
            coordinator.leave_group(group_id).get()
            coordinator.stop()
        except:
            pass


