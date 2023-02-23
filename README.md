## Table of Contents
- [Overview](#overview)
- [Setup](#setup)
- [Development Instructions](#development-instructions)
  * [Generate Config](#generate-config)
    + [Configuring pooler/settings/settings.json](#configuring-pooler-settings-settingsjson)
- [Monitoring and Debugging](#monitoring-and-debugging)
- [For Contributors](#for-contributors)
- [Epoch Generation](#epoch-generation)
- [Major Components](#major-components)
  * [Process Hub Core](#process-hub-core)
  * [System Epoch Detector](#system-epoch-detector)
  * [Processor Distributor](#processor-distributor)
  * [Callback Workers](#callback-workers)
  * [RPC Helper](#rpc-helper)
- [Building Usecases using Pooler](#building-usecases-using-pooler)
  * [Writing the Snapshot Extraction Logic](#writing-the-snapshot-extraction-logic)
  * [Sample UseCase](#sample-usecase)
  * [Project Config](#project-config)
  * [UniswapV2 usecase](#uniswapv2-usecase)

## Overview

![Pooler workflow](https://user-images.githubusercontent.com/9114274/207610006-4b72cd52-1609-4fab-a7d8-311009e9b6d4.png)

Pooler is the component of a fully functional, distributed system that works alongside Audit Protocol, and together they are responsible for
* generating a time series database of changes occurring over smart contract state data and event logs, that live on decentralized storage protocols
* higher order aggregated information calculated over decentralized indexes maintained atop the database mentioned above

Pooler by itself performs the following functions:

1. Tracks the blockchain on which the data source smart contract lives
2. In equally spaced 'epochs'
    * it snapshots raw smart contract state variables, event logs, etc
    * transforms the same
    * and submits these snapshots to audit-protocol


## Setup

Pooler is part of a distributed system with multiple moving parts. The easiest way to get started is by using the docker-based setup from the [deploy](https://github.com/PowerLoom/deploy) repository.

If you're planning to participate as a snapshotter, refer to [these instructions](https://github.com/PowerLoom/deploy#for-snapshotters) to start snapshotting.

If you're a developer, you can follow [this](https://github.com/PowerLoom/deploy#instructions-for-code-contributors) for a more hands on approach.


## Development Instructions
These instructions are needed if you're planning to run the system using `build-dev.sh` from [deploy](https://github.com/PowerLoom/deploy).

### Generate Config
Pooler needs the following config files to be present
1. `settings.json` in `pooler/auth/settings`. This doesn't need much change, you can just copy `settings.example.json` present in the `pooler/auth/settings` directory.
2. `cached_pair_addresses.json` in `pooler/static`, copy over [`static/cached_pair_addresses.example.json`](static/cached_pair_addresses.example.json) to `pooler/static/cached_pair_addresses.json`. These are the pair contracts for uniswapv2 usecase that will be tracked.
3. `settings.json` in `pooler/settings` This one is the main configuration file. We've provided a settings template in `pooler/settings/settings.example.json` to help you get started. Copy over [`settings.example.json`](pooler/settings/settings.example.json) to `pooler/settings/settings.json`

#### Configuring pooler/settings/settings.json
There's a lot of configuration in `settings.json` but to get started, you just need to focus on the following.

- `instance_id`, it is currently generated on invite only basis (refer [deploy](https://github.com/PowerLoom/deploy) repo for more details)
- `namespace`, it is the unique key used to identify your project namespace
- rpc url and rate limit config in `rpc.full_nodes`, this depends on which rpc node you're using
- consensus url in `consensus.url`, this the the offchain-consensus service url where snapshots will be submitted

## Monitoring and Debugging
Login to pooler docker container and use the following commands for monitoring and debugging
- To monitor the status of running processes, you simply need to run `pm2 status`.
- To see all logs you can run `pm2 logs`
- To see logs for a specific process you can run `pm2 logs <Process Identifier>`
- To see only error logs you can run `pm2 logs --err`

## For Contributors
We use [pre-commit hooks](https://pre-commit.com/) to ensure our code quality is maintained over time. For this contributors need to do a one-time setup by running the following commands.
* Install the required dependencies using `pip install -r dev-requirements.txt`, this will setup everything needed for pre-commit checks.
* Run `pre-commit install`

Now, whenever you commit anything, it'll automatically check the files you've changed/edited for code quality issues and suggest improvements.

## Epoch Generation

An epoch denotes a range of block heights on the data source blockchain, Ethereum mainnet in the case of Uniswap v2. This makes it easier to collect state transitions and snapshots of data on equally spaced block height intervals, as well as to support future work on other lightweight anchor proof mechanisms like Merkle proofs, succinct proofs, etc.

The size of an epoch is configurable. Let that be referred to as `size(E)`

- A service keeps track of the head of the chain as it moves ahead, and a marker `h₀` against the max block height from the last released epoch. This makes the beginning of the next epoch, `h₁ = h₀ + 1`

- Once the head of the chain has moved sufficiently ahead so that an epoch can be published, an epoch finalization service takes into account the following factors
    - chain reorganization reports where the reorganized limits are a subset of the epoch qualified to be published
    - a configurable ‘offset’ from the bleeding edge of the chain

 and then publishes an epoch `(h₁, h₂)` so that `h₂ - h₁ + 1 == size(E)`. The next epoch, therefore, is tracked from `h₂ + 1`.



## Major Components
### Process Hub Core
The Process Hub Core, defined in `process_hub_core.py`, serves as the primary process manager in Pooler. Together with `processhub_cmd.py`, it is responsible for starting and managing the `SystemEpochDetector` and `ProcessorDistributor`. Additionally, the Process Hub Core spawns the workers required for processing tasks from the `powerloom-backend-callback` queue. The number of workers and their configuration path can be adjusted in `settings/settings.json`.


### System Epoch Detector

The System Epoch Detector, defined in `system_epoch_detector.py`, is initiated using the `processhub_cmd.py` CLI. Its main role is to detect the latest epoch from our offchain-consensus service, generate epochs of height `h` from the `last_processed_epoch` stored in Redis to the current epoch detected, and push the epochs to the `epoch-broadcast` queue at configured intervals.

### Processor Distributor
The Processor Distributor, defined in `processor_distributor.py`, is initiated using the `processhub_cmd.py` CLI. It reads the epoch detection messages from the `epoch-broadcast` queue, creates and distributes processing messages based on project configuration present in `static/projects.json` to the powerloom-backend-callback queue. This is a topic-based exchange, and the project callback workers listen to this queue to pick up the incoming processing tasks.


### Callback Workers
The Async Callback Worker is defined in `callback_workers.py`. Workers are started initially and load the project snapshot calculation logic defined in `static/projects.json`. Then, they constantly listen to new messages on the `powerloom-backend-callback` queue. Upon receiving a message, the worker does most of the heavy lifting along with some sanity checks and then calls the actual `compute` function defined in the project configuration to read blockchain state and generate the snapshot.


### RPC Helper
Extracting data from blockchain state and generating the snapshot can be a complex task. The `RpcHelper`, defined in `utils/rpc.py`, has a bunch of helper functions to make this process easier. It handles all the `retry` and `caching` logic so that developers can focus on building their use cases in an efficient way.

## Building Usecases using Pooler
Use cases can be anything really. They can be as simple as monitoring some event in a smart contract on some chain and doing some computation over it or complex like monitoring trade stats for all Uniswap top trading pairs. Pooler architecture takes care of most of the heavy lifting involved to make the snapshot creation process as simple as possible.

### Writing the Snapshot Extraction Logic
Since the callback workers invoke the snapshot extraction logic, for every use case, no matter how complex or easy, developers need to write a class with `GenericProcessor` defined in `utils/callback_helpers.py` as parent.


```python
class GenericProcessor(ABC):
    __metaclass__ = ABCMeta

    def __init__(self):
        pass

    @abstractproperty
    def transformation_lambdas(self):
        pass

    @abstractmethod
    async def compute(
        self,
        min_chain_height: int,
        max_chain_height: int,
        data_source_contract_address: str,
        redis: aioredis,
        rpc_helper: RpcHelper,
    ):
        pass

```

There are two main components developers need to focus on.
1. `compute` is the main function where most of the snapshot extraction and generation logic needs to be written. It receives the following inputs:
- `max_chain_height` (epoch end block)
- `min_chain_height` (epoch start block)
- `data_source_contract_address` (contract address to extract data from)
- `redis` (async redis connection)
- `rpc_helper` (RpcHelper instance to help with any blockchain calls necessary)

2. `transformation_lambdas` provide an additional layer for computation on top of the generated snapshot (if needed). If `compute` function handles everything you can just set `transformation_lambdas` to `[]` otherwise pass the list of transformation function sequence. Each function referenced in `transformation_lambdas` must have same input interface. It should receive the following inputs -
 - `snapshot` (the generated snapshot to apply transformation on)
 - `data_source_contract_address` (contract address to extract data from)
 - `epoch_begin` (epoch begin block)
 - `epoch_end` (epoch end block)

Output format can be anything depending on the usecase requirements. Although it is recommended to use proper pydantic models to define the snapshot interface.


### Sample UseCase

Here's an example processor to calculate uniswap v2 pair reserves (simplified version) for a given smart contract.

```python
class PairTotalReservesProcessor(GenericProcessor):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
        self._logger = logger.bind(module='PairTotalReservesProcessor')

    async def compute(
        self,
        min_chain_height: int,
        max_chain_height: int,
        data_source_contract_address: str,
        redis_conn: aioredis,
        rpc_helper: RpcHelper,

    ) -> Optional[Dict[str, Union[int, float]]]:
        epoch_reserves_snapshot_map_token0 = dict()
        epoch_reserves_snapshot_map_token1 = dict()
        epoch_usd_reserves_snapshot_map_token0 = dict()
        epoch_usd_reserves_snapshot_map_token1 = dict()
        max_block_timestamp = int(time.time())

        try:
            self._logger.debug(f'pair reserves {data_source_contract_address} computation init time {time.time()}')
            pair_reserve_total = await get_pair_reserves(
                pair_address=data_source_contract_address,
                from_block=min_chain_height,
                to_block=max_chain_height,
                redis_conn=redis_conn,
                rpc_helper=rpc_helper,
                fetch_timestamp=True,
            )
        except Exception as exc:
            self._logger.opt(exception=True).error(
                (
                    'Pair-Reserves function failed for epoch:'
                    f' {min_chain_height}-{max_chain_height} | error_msg:{exc}'
                ),
            )
            # if querying fails, we are going to ensure it is recorded for future processing
            return None
        else:
            for block_num in range(min_chain_height, max_chain_height + 1):
                block_pair_total_reserves = pair_reserve_total.get(block_num)

                epoch_reserves_snapshot_map_token0[
                    f'block{block_num}'
                ] = block_pair_total_reserves['token0']
                epoch_reserves_snapshot_map_token1[
                    f'block{block_num}'
                ] = block_pair_total_reserves['token1']
                epoch_usd_reserves_snapshot_map_token0[
                    f'block{block_num}'
                ] = block_pair_total_reserves['token0USD']
                epoch_usd_reserves_snapshot_map_token1[
                    f'block{block_num}'
                ] = block_pair_total_reserves['token1USD']

                max_block_timestamp = block_pair_total_reserves.get(
                    'timestamp',
                )
            pair_total_reserves_snapshot = UniswapPairTotalReservesSnapshot(
                **{
                    'token0Reserves': epoch_reserves_snapshot_map_token0,
                    'token1Reserves': epoch_reserves_snapshot_map_token1,
                    'token0ReservesUSD': epoch_usd_reserves_snapshot_map_token0,
                    'token1ReservesUSD': epoch_usd_reserves_snapshot_map_token1,
                    'chainHeightRange': EpochBase(
                        begin=min_chain_height, end=max_chain_height,
                    ),
                    'timestamp': max_block_timestamp,
                    'contract': data_source_contract_address,
                },
            )
            self._logger.debug(f'pair reserves {data_source_contract_address}, computation end time {time.time()}')

            return pair_total_reserves_snapshot

```

### Project Config
The configuration for all usecases in defined in `static/projects.json` and looks something like this

```json
{
  "config": [{
      "project_type": "uniswap_pairContract_pair_total_reserves",
      "projects":[
        "0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc",
        "0x21b8065d10f73ee2e260e5b47d3344d3ced7596e",
        ],
      "processor":{
        "module": "pooler.modules.uniswapv2.pair_total_reserves",
        "class_name": "PairTotalReservesProcessor"
      }
    },
    {
      "project_type": "uniswap_pairContract_trade_volume",
      "projects":[
        "0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc",
        "0x21b8065d10f73ee2e260e5b47d3344d3ced7596e",
        ],
        "processor":{
          "module": "pooler.modules.uniswapv2.trade_volume",
          "class_name": "TradeVolumeProcessor"
        }
    }
  ]
}

```

It basically takes a list of project configs in config. Each project config needs to have the following components

- `project_type` (unique identifier for the usecase)
- `projects` (smart contracts to extract data from, pooler can generate different snapshots from multiple sources as long as the Contract ABI is same)
- `processor` (the actual compuation logic reference, while you can write the logic anywhere, it is recommended to write your implementation in pooler/modules folder)

There's currently no limitation on the number or type of usecases you can build using pooler. Just write the Processor class and pooler libraries will take care of the rest.


### UniswapV2 usecase
The uniswapv2 usecase present in `pooler/modules/uniswapv2` aims to generate snapshots for the following most frequently sought data points on UniswapV2.
    - Total Value Locked (TVL)
    - Trade Volume, Liquidity reserves, Fees earned
        - grouped by
            - Pair contracts
            - Individual tokens participating in pair contract
        - aggregated overtime periods
            - 24 hours
            - 7 days
    - Transactions containing `Swap`, `Mint`, and `Burn` events


You can read more about Audit Protocol and the Uniswap v2 PoC in the  [Powerloom Protocol Overview document](https://www.notion.so/powerloom/PowerLoom-Protocol-Overview-c3bf9dd9323541118d46a4d8684565d1#8ad76b8362b341bcaa9b3ae9fe203271)
