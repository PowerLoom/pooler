## Table of Contents
- [Overview](#overview)
- [Setup](#setup)
- [State transitions and data composition](#state-transitions-and-data-composition)
    * [Epoch Generation](#epoch-generation)
    * [Base snapshot generation](#base-snapshot-generation)
    * [Snapshot Finalization](#snapshot-finalization)
    * [Aggregation and data composition](#aggregation-and-data-composition---snapshot-generation)
- [Development Instructions](#development-instructions)
  * [Configuration](#configuration)
- [Monitoring and Debugging](#monitoring-and-debugging)
- [For Contributors](#for-contributors)
- [Major Components](#major-components)
  * [System Event Detector](#system-event-detector)
  * [Process Hub Core](#process-hub-core)
  * [System Epoch Detector](#system-epoch-detector)
  * [Processor Distributor](#processor-distributor)
  * [Callback Workers](#callback-workers)
  * [RPC Helper](#rpc-helper)
- [Building Usecases using Pooler](#building-usecases-using-pooler)
  * [Writing the Snapshot Extraction Logic](#writing-the-snapshot-extraction-logic)
  * [Sample UseCase](#sample-usecase)
  * [Project Config](#project-config)

## Overview

![Pooler workflow](pooler/static/docs/assets/README%20overall%20architecture.png)


Pooler is a Uniswap specific implementation of what is known as a 'snapshotter' in the PowerLoom Protocol ecosystem. It synchronizes with other snapshotter peers over a smart contract running on the present version of the PowerLoom Protocol testnet. It follows an architecture that is driven by state transitions which makes it easy to understand and modify. This present release ultimately provide access to rich aggregates that can power a Uniswap v2 dashboard with the following data points:

- Total Value Locked (TVL)
- Trade Volume, Liquidity reserves, Fees earned
    - grouped by
        - Pair contracts
        - Individual tokens participating in pair contract
    - aggregated over time periods
        - 24 hours
        - 7 days
- Transactions containing `Swap`, `Mint`, and `Burn` events



In its last release (link to github commit or tag here), pooler was a *self contained* system that would provide access to the above. The present implementation differs from that in some major ways:

* each data point is calculated, updated and synchronized with other snapshotter peers participating in the network for this Uniswap v2 use case
* synchronization of data points is defined as a function of an epoch ID(entifier) where epoch refers to an equally spaced collection of blocks on the data source smart contract's chain (Ethereum mainnet in case of Uniswap v2). This simplifies building of use cases that are stateful (i.e. can be accessed according to their state at a given height of the data source chain), synchronized and depend on reliable data. For example,
    * dashboards by offering higher order aggregate datapoints
    * trading strategies and bots
* a snapshotter peer can now load past epochs, indexes and aggregates from a decentralized state and have access to a rich history of data
    * earlier a stand alone node would have differing aggregate datapoints from other such nodes running independently, and even though the datasets were decentralized on IPFS/Filecoin, the power of these decentralized storage networks could not be leveraged fully since the content identifiers would often be different without any coordinating pivot like a decentralized state or smart contract on which all peers had to agree.


## Setup

Pooler is part of a distributed system with multiple moving parts. The easiest way to get started is by using the docker-based setup from the [deploy](https://github.com/PowerLoom/deploy) repository.

If you're planning to participate as a snapshotter, refer to [these instructions](https://github.com/PowerLoom/deploy#for-snapshotters) to start snapshotting.

If you're a developer, you can follow [this](https://github.com/PowerLoom/deploy#instructions-for-code-contributors) for a more hands on approach.

**Note** - RPC usage is highly use case specific. If your use case is complicated and needs to make a lot of RPC calls, it is recommended to run your own RPC node instead of using third party RPC services as it can be expensive.

## State transitions and data composition

### Epoch Generation

An epoch denotes a range of block heights on the data source blockchain, Ethereum mainnet in the case of Uniswap v2. This makes it easier to collect state transitions and snapshots of data on equally spaced block height intervals, as well as to support future work on other lightweight anchor proof mechanisms like Merkle proofs, succinct proofs, etc.

The size of an epoch is configurable. Let that be referred to as `size(E)`

- A trusted service keeps track of the head of the chain as it moves ahead, and a marker `h₀` against the max block height from the last released epoch. This makes the beginning of the next epoch, `h₁ = h₀ + 1`

- Once the head of the chain has moved sufficiently ahead so that an epoch can be published, an epoch finalization service takes into account the following factors
    - chain reorganization reports where the reorganized limits are a subset of the epoch qualified to be published
    - a configurable ‘offset’ from the bleeding edge of the chain

 and then publishes an epoch `(h₁, h₂)` by sending a transaction to the protocol state smart contract deployed on the Prost Chain (anchor chain) so that `h₂ - h₁ + 1 == size(E)`. The next epoch, therefore, is tracked from `h₂ + 1`.

 Each such transaction emits an `EpochReleased` event 

 ```
 event EpochReleased(uint256 indexed epochId, uint256 begin, uint256 end, uint256 timestamp);
 ```

 The `epochId` here is incremented by 1 with every successive epoch release.

 ### Base Snapshot Generation

 Workers in [`config/projects.json`](config/projects.example.json) calculate base snapshots against this `epochId` which corresponds to collections of state observations and event logs between the blocks at height in the range `[begin, end]`, per Uniswap v2 pair contract. Each such pair contract is assigned a project ID on the protocol state contract according to the following format:

`{project_type}:{pair_contract_address}:{settings.namespace}`
 
 The snapshots generated by workers defined in this config are the fundamental data models on which higher order aggregates and richer datapoints are built.

 ### Snapshot Finalization

All snapshots per project reach consensus on the protocol state contract which results in a `SnapshotFinalized` event being triggered. 

This helps us in building sophisticated aggregates, super-aggregates, filters and other forms of data composition on top of base snapshots. 

```
event SnapshotFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string snapshotCid, uint256 timestamp);
```

### Aggregation and data composition - snapshot generation

Workers as defined in `config/aggregator.json` are triggered by the appropriate signals forwarded to [`Processor Distributor`](pooler/processor_distributor.py) corresponding to the project ID filters as explained in the [Configuration](#configuration) section.

![Data composition](pooler/static/docs/assets/DataComposition.png)

## Development Instructions
These instructions are needed if you're planning to run the system using `build-dev.sh` from [deploy](https://github.com/PowerLoom/deploy).

### Configuration
Pooler needs the following config files to be present
* **`settings.json` in `pooler/auth/settings`**: Changes are trivial. Copy [`config/auth_settings.example.json`](config/auth_settings.example.json) to `config/auth_settings.json`. This enables an authentication layer over the core API exposed by the pooler snapshotter.
* settings file in `config/`
    * **`config/projects.json`**: This lists out the smart contracts on the data source chain on which snapshots will be generated paired with the snapshot worker class. It's an array of objects with the following structure:
        ```javascript
        {
            "project_type": "snapshot_project_name_prefix_",
            "projects": ["array of smart contract addresses"], // Uniswap v2 pair contract addresses in this implementation
            "processor":{
                "module": "pooler.modules.uniswapv2.pair_total_reserves", 
                "class_name": "PairTotalReservesProcessor" // class to be found in module pooler/modules/uniswapv2/pair_total_reserves.py
            }
        }
        ```
        Copy over [`config/projects.example.json`](config/projects.example.json) to `config/projects.json`. For more details, read on in the [section below on extending a use case](#configuring-poolersettingssettingsjson).
    * **`config/aggregator.json`** : This lists out different type of aggregation work to be performed over a span of snapshots. Copy over [`config/aggregator.example.json`](config/aggregator.example.json) to `config/aggregator.json`. The span is usually calculated as a function of the epoch size and average block time on the data source network. For eg, 
        * the following configuration calculates a snapshot of total trade volume over a 24 hour time period, based on the [snapshot finalization](#snapshot-finalization) of a project ID corresponding to a pair contract. This can be seen by the `aggregate_on` key being set to `SingleProject`.
            * This is specified by the `filters` key below. If a snapshot finalization is achieved for an epoch over a project ID [(ref:generation of project ID for snapshot building workers)](#epoch-generation) `uniswap_pairContract_trade_volume:0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc:UNISWAPV2-ph15-prod`, this would trigger the worker [`AggreagateTradeVolumeProcessor`](pooler/modules/uniswapv2/aggregate/single_uniswap_trade_volume_24h.py) as defined in the `processor` section of the config against the pair contract `0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc`. 
        ```javascript
        {
            "config": [
                {
                    "project_type": "aggregate_uniswap_pairContract_24h_trade_volume",
                    "aggregate_on": "SingleProject",
                    "filters": {
                        "projectId": "uniswap_pairContract_trade_volume"
                    },
                    "processor": {
                        "module": "pooler.modules.uniswapv2.aggregate.single_uniswap_trade_volume_24h",
                        "class_name": "AggreagateTradeVolumeProcessor"
                    }
                }
            ]
        }
        ```
        * The following configuration generates a collection of data sets of 24 hour trade volume as calculated by the worker above across multiple pair contracts. This can be seen by the `aggregate_on` key being set to `MultiProject`.
            * `projects_to_wait_for` specifies the exact project IDs on which this collection will be generated once a snapshot finalized event has been received for an [`epochId`](#epoch-generation). 
        ```javascript
        {
            "config": [
                "project_type": "aggregate_uniswap_24h_top_pairs",
                "aggregate_on": "MultiProject",
                "projects_to_wait_for": [
                    "aggregate_uniswap_pairContract_24h_trade_volume:0xa478c2975ab1ea89e8196811f51a7b7ade33eb11:UNISWAPV2-ph15-prod",
                    "uniswap_pairContract_pair_total_reserves:0xa478c2975ab1ea89e8196811f51a7b7ade33eb11:UNISWAPV2-ph15-prod",
                    "aggregate_uniswap_pairContract_24h_trade_volume:0x11181bd3baf5ce2a478e98361985d42625de35d1:UNISWAPV2-ph15-prod",
                    "uniswap_pairContract_pair_total_reserves:0x11181bd3baf5ce2a478e98361985d42625de35d1:UNISWAPV2-ph15-prod"
                ],
                "processor": {
                    "module": "pooler.modules.uniswapv2.aggregate.multi_uniswap_top_pairs_24h",
                    "class_name": "AggreagateTopPairsProcessor"
                }
            ]
        }
        ```

        ![Aggregation Workflow](pooler/static/docs/assets/AggregationWorkflow.png)
* To begin with, you can keep the workers and contracts as specified in the example files.

* **`config/settings.json`**: This is the primary configuration. We've provided a settings template in `config/settings.example.json` to help you get started. Copy over [`config/settings.example.json`](config/settings.example.json) to `config/settings.json`. There can be a lot to fine tune but the following are essential.
    - `instance_id`: This is the unique public key for your node to participate in consensus. It is currently registered on approval of an application (refer [deploy](https://github.com/PowerLoom/deploy) repo for more details on applying).
    - `namespace`, it is the unique key used to identify your project namespace around which all consensus activity takes place.
    - RPC service URL(s) and rate limit configurations. Rate limits are service provider specific, different RPC providers have different rate limits. Example rate limit config for a node looks something like this `"100000000/day;20000/minute;2500/second"`
        - **`rpc.full_nodes`**: This will correspond to RPC nodes for the chain on which the data source smart contracts lives (for eg. Ethereum Mainnet, Polygon Mainnet etc). 
        - **`anchor_chain_rpc.full_nodes`**: This will correspond to RPC nodes for the anchor chain on which the protocol state smart contract lives (Prost Chain). 
        - **`protocol_state.address`** : This will correspond to the address at which the protocol state smart contract is deployed on the anchor chain. **`protocol_state.abi`** is already filled in the example and already available at the static path specified [`pooler/static/abis/ProtocolContract.json`](pooler/static/abis/ProtocolContract.json)
 

## Monitoring and Debugging
Login to pooler docker container using `docker exec -it deploy-pooler-1 bash` (use `docker ps` to verify its presence in the list of running containers) and use the following commands for monitoring and debugging
- To monitor the status of running processes, you simply need to run `pm2 status`.
- To see all logs you can run `pm2 logs`
- To see logs for a specific process you can run `pm2 logs <Process Identifier>`
- To see only error logs you can run `pm2 logs --err`

## For Contributors
We use [pre-commit hooks](https://pre-commit.com/) to ensure our code quality is maintained over time. For this contributors need to do a one-time setup by running the following commands.
* Install the required dependencies using `pip install -r dev-requirements.txt`, this will setup everything needed for pre-commit checks.
* Run `pre-commit install`

Now, whenever you commit anything, it'll automatically check the files you've changed/edited for code quality issues and suggest improvements.



## Major Components

### System Event Detector

The system event detector tracks events being triggered on the protocol state contract running on the anchor chain and forwards it to a callback queue with the appropriate routing key depending on the event signature and type among other information.

Related information and other services depending on these can be found in previous sections: [State Transitions](#state-transitions), [Configuration](#configuration).


### Process Hub Core
The Process Hub Core, defined in `process_hub_core.py`, serves as the primary process manager in Pooler. Together with `processhub_cmd.py`, it is responsible for starting and managing the `SystemEventDetector` and `ProcessorDistributor`. Additionally, the Process Hub Core spawns the workers required for processing tasks from the `powerloom-backend-callback` queue. The number of workers and their configuration path can be adjusted in `config/settings.json`.

### Processor Distributor
The Processor Distributor, defined in `processor_distributor.py`, is initiated using the `processhub_cmd.py` CLI. It reads the epoch detection messages from the `epoch-broadcast` queue, creates and distributes processing messages based on project configuration present in `static/projects.json` to the powerloom-backend-callback queue. This is a topic-based exchange, and the project callback workers listen to this queue to pick up the incoming processing tasks.


### Callback Workers
The Async Callback Worker is defined in `callback_workers.py`. Workers are started initially and load the project snapshot calculation logic defined in `static/projects.json`. Then, they constantly listen to new messages on the `powerloom-backend-callback` queue. Upon receiving a message, the worker does most of the heavy lifting along with some sanity checks and then calls the actual `compute` function defined in the project configuration to read blockchain state and generate the snapshot.


### RPC Helper
Extracting data from blockchain state and generating the snapshot can be a complex task. The `RpcHelper`, defined in `utils/rpc.py`, has a bunch of helper functions to make this process easier. It handles all the `retry` and `caching` logic so that developers can focus on building their use cases in an efficient way.

## Building Usecases using Pooler
Use cases can be anything really. They can be as simple as monitoring some event in a smart contract on some chain and doing some computation over it or complex like monitoring trade stats for all Uniswap top trading pairs. Pooler architecture takes care of most of the heavy lifting involved to make the snapshot creation process as simple as possible.

### Writing the Snapshot Extraction Logic
Since the callback workers invoke the snapshot extraction logic, for every use case, no matter how complex or easy, developers need to write a class with `GenericProcessorSnapshot` defined in `utils/callback_helpers.py` as parent.


```python
class GenericProcessorSnapshot(ABC):
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
        redis: aioredis.Redis,
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
class PairTotalReservesProcessor(GenericProcessorSnapshot):
    transformation_lambdas = None

    def __init__(self) -> None:
        self.transformation_lambdas = []
        self._logger = logger.bind(module='PairTotalReservesProcessor')

    async def compute(
        self,
        min_chain_height: int,
        max_chain_height: int,
        data_source_contract_address: str,
        redis_conn: aioredis.Redis,
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


You can read more about Audit Protocol and the Uniswap v2 PoC in the  [Powerloom Protocol Overview document](https://www.notion.so/powerloom/PowerLoom-Protocol-Overview-c3bf9dd9323541118d46a4d8684565d1#8ad76b8362b341bcaa9b3ae9fe203271)
