## Architecture
The high-level architecture of the single-node Pooler system is shown below.
![PowerloomSingleNodeSystem-Overall Architecture drawio (2)-Overall Architecture drawio](https://user-images.githubusercontent.com/9114274/207516466-61ef36f6-0856-4a15-b8b5-3101b0362b2e.png)

## RabbitMQ Initialization

Just like the name suggests, the `init_rabbitmq.py` file sets up the various queues required for Pooler to function. At the top level, there are two types of queues, exchange queues, and callback queues. 
Callback Queue is consumed by workers to generate the actual snapshot data (see the `callback_modules` folder) to be submitted to Audit Protocol.
Exchange queues are usually used for high-level operations like Epoch notifications etc.

This is a one-time task that users need to do when they run the pooler for the first time (detailed instructions are present in the README.md file).

## TODO: Add section for overall working and flow 

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
