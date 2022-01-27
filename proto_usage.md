# Launch or restart ProcessHub Core 

`pm2 start launch_process_hub_core.py --name=poly-adapter-processhub-core`

`pm2 restart poly-adapter-processhub-core`

# Stop ProcessHub Core 

`pm2 stop poly-adapter-processhub-core`

# Shutdown Thespian Actor System after shutting down processhub core 

`python actor_sys_shutdown.py`

# Logs

`pm2 start proto_system_logging_server.py --name=poly-adapter-central-logging`

## Central logging 

`pm2 logs poly-adapter-central-logging`

## Polymarket smart contract events listener logs 

`tail -f logs/contract_event_listener-<TIMESTAMP>-out.log`

`tail -f logs/contract_event_listener-<TIMESTAMP>-err.log`

# Check error logs on ProcessHub Core STDERR stream from  spawned processes if some messages are lost in transit to central logging server 

`pm2 logs poly-adapter-processhub-core --err ` 


# Prototype CLI to interact with ProcessHub 

## Start services
`python processhub_cmd.py start SmartContractsEventsListener`

`python processhub_cmd.py start EpochCallbackManager`

`python processhub_cmd.py start SystemEpochFinalizer`

`python processhub_cmd.py start SystemEpochCollator`

`python processhub_cmd.py start SystemLinearEpochClock`


## Stop services

`python processhub_cmd.py stop SystemLinearEpochClock`

`python processhub_cmd.py stop SystemEpochFinalizer`

`python processhub_cmd.py stop SystemEpochCollator`

`python processhub_cmd.py stop EpochCallbackManager`

`python processhub_cmd.py stop SmartContractsEventsListener`

## List processes spawned by ProcessHub Core

`python processhub_cmd.py listprocesses`

## List recently sent out broadcasts 

`python processhub_cmd.py listbroadcasts 300` -- lists broadcasts sent out in the last 300 seconds

## List status of processing of epochs that have been broadcast recently

`python processhub_cmd.py listcallbackstatus`
