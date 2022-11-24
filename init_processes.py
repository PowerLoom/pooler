from message_models import ProcessHubCommand
from init_rabbitmq import create_rabbitmq_conn, processhub_command_publish


def main():
    # init_exchanges_queues()
    # core = ProcessHubCore('PowerLoomProcessHub')
    # core.start()
    c = create_rabbitmq_conn()
    ch = c.channel()
    start_contract_event_listener_cmd = ProcessHubCommand(command='start', proc_str_id='SmartContractsEventsListener')
    processhub_command_publish(ch, start_contract_event_listener_cmd.json())

    start_epoch_finalizer_cmd = ProcessHubCommand(command='start', proc_str_id='SystemEpochFinalizer')
    processhub_command_publish(ch, start_epoch_finalizer_cmd.json())

    start_epoch_collator_cmd = ProcessHubCommand(command='start', proc_str_id='SystemEpochCollator')
    processhub_command_publish(ch, start_epoch_collator_cmd.json())

    start_linear_epoch_cmd = ProcessHubCommand(command='start', proc_str_id='SystemLinearEpochClock')
    processhub_command_publish(ch, start_linear_epoch_cmd.json())

    start_market_processor_cmd = ProcessHubCommand(command='start', proc_str_id='MarketMakerContractsProcessor')
    processhub_command_publish(ch, start_market_processor_cmd.json())


if __name__ == '__main__':
    main()
