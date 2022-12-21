## Architecture
The high-level architecture of the Pooler system is shown below.
![PowerloomSingleNodeSystem-Overall Architecture drawio (2)-Overall Architecture-Overall Architecture(1)](https://user-images.githubusercontent.com/9114274/208616540-127bd7fa-f8c6-4e94-8ddd-ba1249f32811.jpg)



## RabbitMQ Initialization

Just like the name suggests, the `init_rabbitmq.py` file sets up the various queues required for Pooler to function. At the top level, there are two types of queues, exchange queues, and callback queues. 
Callback Queue is consumed by workers to generate the actual snapshot data (see the `callback_modules` folder) to be submitted to Audit Protocol.
Exchange queues are usually used for high-level operations like Epoch notifications etc.

This is a one-time task that users need to do when they run the pooler for the first time (detailed instructions are present in the README.md file).


## System Epoch Detector
The system epoch detector is defined in `system_epoch_detector.py` and is and is initiated using the `processhub_cmd.py` CLI. 
The main role of this process is to detect the latest epoch from our `offchain-consensus` service, Generate epochs of height `h` from the `last_processed_epoch` stored in redis to the current epoch detected and push the epochs to `epoch-broadcast` queue at configured intervals.

## Epoch Callback Manager
The epoch callback manager is defined in `epoch_broadcast_callback_manager.py` and is also initiated using the `processhub_cmd.py` CLI.
It reads the messages from `epoch-broadcast` queue, adds a little extra helper context like contract_addresses for uniswap v2 pairs, 
sends the messages to relavant routing channels according to topics defined in callback modules (see callback_modules/module_queue_config.json) and pushes the task to `backend-callbacks` queue.

## Process Hub Core
Process Hub Core (defined in `process_hub_core.py`) is the main process manager in Pooler. It in combination with `processhub_cmd.py` is used to start and manage `System Block Epoch Ticker`, `System Epoch Collator`, `System Epoch Finalizer`, and `Epoch Callback Manager`. Process Hub Core is also responsible for spawing up the worker threads required for processing tasks from the `backend-callbacks` queue. These workers and their configuration is read from `callback_modules/module_queues_config.json`.

## Server
The main FastAPI server and entry point for this module is `core_api.py`, this server is started using a custom Gunicorn handler present in `gunicorn_core_launcher.py`. Doing so provides more flexibility to customize the application and start it using `Pm2`. `core_api.py` provides multiple API endpoints to interact with the snapshotted data in various ways.


## Helpers and Utilities
### Clean Slate
`clean_slate.py` can be used to clean up Redis and IPFS data.

### Process Hub CLI
`processhub_cmd.py` acts as a CLI tool to interact with `process_hub_core`. This CLI is used to start various processes like `EpochCallbackManager` through the `process_hub_core_modules`.

### Exceptions
`exceptions.py` declares custom Exceptions used across the project.

### File Utils
`file_utils.py` contains helper functions like reading from and writing to `JSON` files.

### RPC Helper
`rpc_helper.py` contains helper functions to help interact with RPC endpoints like making batch_calls (calling multiple contract functions in a single RPC call) etc.

### Redis Utilities
`redis_conn.py` contains utility and helper functions for Redis pool setup and `redis_keys.py` contains functions to generate all the `keys` that are used in Redis across the entire module.

### Other Utilities
`rate_limiter.py` and `utility_functions.py` contain helper functions for rate limiting using Redis and some other generic utilities.

`launch_process_hub_core.py` is used to initialize necessary RabbitMQ queues and start the `process_hub_core` with a custom title (for cleaner process management using Pm2) 
