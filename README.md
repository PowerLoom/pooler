## Table of Contents
- [Table of Contents](#table-of-contents)
- [Overview](#overview)
  - [Architecture](#architecture)
- [Setup](#setup)
  - [Epoch Generation](#epoch-generation)
  - [Snapshot Generation](#snapshot-generation)
    - [Bulk Mode](#bulk-mode)
  - [Data source signaling](#data-source-signaling)
  - [Snapshot Finalization](#snapshot-finalization)
- [Major Components](#major-components)
  - [System Event Detector](#system-event-detector)
  - [Process Hub Core](#process-hub-core)
  - [Processor Distributor](#processor-distributor)
  - [RPC Helper](#rpc-helper)
  - [Core API](#core-api)
- [Monitoring and Debugging](#monitoring-and-debugging)
- [For Contributors](#for-contributors)
- [Case Studies](#case-studies)
  - [1. Pooler: Case study and extending this implementation](#1-pooler-case-study-and-extending-this-implementation)
    - [Extending pooler with a Uniswap v2 data point](#extending-pooler-with-a-uniswap-v2-data-point)
      - [Step 1. Review: Base snapshot extraction logic for trade information](#step-1-review-base-snapshot-extraction-logic-for-trade-information)
  - [2. Zkevm Quests: A Case Study of Implementation](#2-zkevm-quests-a-case-study-of-implementation)
    - [Review: Base snapshots](#review-base-snapshots)
    - [`zkevm:bungee_bridge`](#zkevmbungee_bridge)
- [Find us](#find-us)

## Overview

![Snapshotter workflow](snapshotter/static/docs/assets/OverallArchitecture.png)

A snapshotter peer as part of Powerloom Protocol does exactly what the name suggests:  It synchronizes with other snapshotter peers over a smart contract running on Powerloom Prost chain. It follows an architecture that is driven by state transitions which makes it easy to understand and modify.

Because of its decentralized nature, the snapshotter specification and its implementations share some powerful features that can adapt to your specific information requirements on blockchain applications:

* Each data point is calculated, updated, and synchronized with other snapshotter peers participating in the network
* synchronization of data points is defined as a function of an epoch ID(identifier) where epoch refers to an equally spaced collection of blocks on the data source blockchain (for eg, Ethereum Mainnet/Polygon Mainnet/Polygon Testnet -- Mumbai). This simplifies the building of use cases that are stateful (i.e. can be accessed according to their state at a given height of the data source chain), synchronized, and depend on reliable data. For example,
    * dashboards by offering higher-order aggregate datapoints
    * trading strategies and bots
* a snapshotter peer can load past epochs, indexes, and aggregates from a decentralized state and have access to a rich history of data
    * all the datasets are decentralized on IPFS/Filecoin
    * the power of these decentralized storage networks can be leveraged fully by applying the [principle of composability](#aggregation-and-data-composition---snapshot-generation-of-higher-order-datapoints-on-base-snapshots)

### Architecture

The Snapshotter Peer is thoughtfully designed with a modular and highly configurable architecture, allowing for easy customization and seamless integration. It consists of three core components:

1. **Main Snapshotter Codebase**:
   - This foundational component defines all the essential interfaces and handles a wide range of tasks, from listening to epoch release events to distributing tasks and managing snapshot submissions.

2. **Configuration Files**:
   - Configuration files, located in the `/config` directory are linked to [snapshotter-configs](https://github.com/PowerLoom/snapshotter-configs/) repo, play a pivotal role in defining project types, specifying paths for individual compute modules, and managing various project-related settings.

3. **Compute Modules**:
   - The heart of the system resides in the `snapshotter/modules` directory are linked to [snapshotter-computes](https://github.com/PowerLoom/snapshotter-computes/), where the actual computation logic for each project type is defined. These modules drive the snapshot generation process for specific project types.

![Snapshotter Architecture](snapshotter/static/docs/assets/SnapshotterArchitecture.png)

The architecture has been designed to facilitate the seamless interchange of configuration and modules. To achieve this, we maintain these components in separate Git repositories, which are then integrated into the Snapshotter Peer using Git Submodules. As a result, adapting the system to different use cases is as straightforward as changing a Git branch, offering unparalleled flexibility and versatility.

For more information on using Git Submodules, please refer to the [Git Submodules Documentation](https://git-scm.com/book/en/v2/Git-Tools-Submodules).

## Setup

The snapshotter is a distributed system with multiple moving parts. The easiest way to get started is by using the Docker-based setup according to the instructions in the section: [Development setup and instructions](#development-setup-and-instructions).

If you're planning to participate as a snapshotter, refer to [these instructions](https://github.com/PowerLoom/deploy#for-snapshotters) to start snapshotting.

If you're a developer, you can follow the [manual configuration steps for pooler](#configuration) from this document followed by the [instructions on the `deploy` repo for code contributors](https://github.com/PowerLoom/deploy#instructions-for-code-contributors) for a more hands-on approach.

**Note** - RPC usage is highly use-case specific. If your use case is complicated and needs to make a lot of RPC calls, it is recommended to run your own RPC node instead of using third-party RPC services as it can be expensive.


### Epoch Generation

An epoch denotes a range of block heights on the EVM-compatible data source blockchain, for eg Ethereum mainnet/Polygon PoS mainnet/testnet. This makes it easier to collect state transitions and snapshots of data on equally spaced block height intervals, as well as to support future work on other lightweight anchor proof mechanisms like Merkle proofs, succinct proofs, etc.

The size of an epoch is configurable. Let that be referred to as `size(E)`

- A [trusted service](https://github.com/PowerLoom/onchain-consensus) keeps track of the head of the chain as it moves ahead, and a marker `h₀` against the max block height from the last released epoch. This makes the beginning of the next epoch, `h₁ = h₀ + 1`

- Once the head of the chain has moved sufficiently ahead so that an epoch can be published, an epoch finalization service takes into account the following factors
    - chain reorganization reports where the reorganized limits are a subset of the epoch qualified to be published
    - a configurable ‘offset’ from the bleeding edge of the chain

 and then publishes an epoch `(h₁, h₂)` by sending a transaction to the protocol state smart contract deployed on the Prost Chain (anchor chain) so that `h₂ - h₁ + 1 == size(E)`. The next epoch, therefore, is tracked from `h₂ + 1`.

 Each such transaction emits an `EpochReleased` event

 ```
 event EpochReleased(uint256 indexed epochId, uint256 begin, uint256 end, uint256 timestamp);
 ```

 The `epochId` here is incremented by 1 with every successive epoch release.


### Snapshot Generation

 Workers, as mentioned in the configuration section for [`config/projects.json`](#configuration), calculate base snapshots against this `epochId` which corresponds to collections of state observations and event logs between the blocks at height in the range `[begin, end]`.

 The data sources are determined according to the following specification for the `projects` key:

 * an empty array against the `projects` indicates no specific data source is defined
 * an array of EVM-compatible wallet address strings can also be listed
 * an array of "<addr1>_<addr2>" strings that denote the relationship between two EVM addresses (for eg ERC20 balance of `addr2` against a token contract `addr1`)
 * data sources can be dynamically added on the protocol state contract which the [processor distributor](#processor-distributor) [syncs with](https://github.com/PowerLoom/pooler/blob/d8b7be32ad329e8dcf0a7e5c1b27862894bc990a/snapshotter/processor_distributor.py#L1107):

The project ID is ultimately generated in the following manner:

https://github.com/PowerLoom/pooler/blob/d8b7be32ad329e8dcf0a7e5c1b27862894bc990a/snapshotter/utils/snapshot_worker.py#L51-L71


 The snapshots generated by workers defined in this config are the fundamental data models on which higher-order aggregates and richer data points are built. The `SnapshotSubmitted` event generated on such base snapshots further triggers the building of sophisticated aggregates, super-aggregates, filters, and other data composites on top of them.

#### Bulk Mode

For situations where data sources are constantly changing or numerous, making it impractical to maintain an extensive list of them, the Snapshotter Peer offers a Bulk Mode. This feature is particularly useful in scenarios where specific data sources need not be defined explicitly.

In Bulk Mode, the system monitors all transactions and blocks without the need for predefined data sources. The Processor Distributor generates a `SnapshotProcessMessage` with bulk mode enabled for each project type. When snapshot workers receive this message, they leverage preloaded transaction receipts for entire blocks, filtering out relevant transactions to generate snapshots for all data sources that interacted with the blockchain during that epoch. Snapshot worker then generates relevant project Ids for these snapshots and submits them for further processing.

Bulk Mode is highly effective in situations where the project list is continually expanding or where snapshots don't need to be submitted in every epoch, perhaps because the data hasn't changed significantly. Example use cases include monitoring on-chain activities and tracking task or quest completion statuses on the blockchain.

An important advantage of Bulk Mode is that, since all transaction receipts are preloaded, this approach can efficiently scale to accommodate a large number of project types with little to no increase in RPC (Remote Procedure Call) calls.

https://github.com/PowerLoom/pooler/blob/d8b7be32ad329e8dcf0a7e5c1b27862894bc990a/snapshotter/utils/snapshot_worker.py#L260-L299

 ### Data source signaling

 As seen above in the section on [base snapshot generation](#base-snapshot-generation), data sources can be dynamically added to the contract according to the role of certain peers in the ecosystem known as 'signallers'. This is the most significant aspect of the Powerloom Protocol ecosystem apart from snapshotting and will soon be decentralized to factor in on-chain activity, and market forces and accommodate a demand-driven, dynamic data ecosystem.

In the existing setup, when the `project_type` is set to an empty array (`[]`) and bulk mode is not activated, the snapshotter node attempts to retrieve data sources corresponding to the `projects` key from the protocol state contract.

Whenever a data source is added or removed by a combination of the data source-detector and signaller, the protocol state smart contract emits a `ProjectUpdated` event, adhering to the defined data model.

https://github.com/PowerLoom/pooler/blob/5892eeb9433d8f4b8aa677006d98a1dde0458cb7/snapshotter/utils/models/data_models.py#L102-L105

The snapshotting for every such dynamically added project is initiated only when the `epochId`, corresponding to the field `enableEpochId` contained within the `ProjectUpdated` event, is released. The [processor distributor](#processor-distributor) correctly triggers the snapshotting workflow for such dynamically added data sources in the following segment:

https://github.com/PowerLoom/pooler/blob/d8b7be32ad329e8dcf0a7e5c1b27862894bc990a/snapshotter/processor_distributor.py#L765-L796



 ### Snapshot Finalization

All snapshots per project reach consensus on the protocol state contract which results in a `SnapshotFinalized` event being triggered.

```
event SnapshotFinalized(uint256 indexed epochId, uint256 epochEnd, string projectId, string snapshotCid, uint256 timestamp);
```


## Major Components

![Snapshotter Components](snapshotter/static/docs/assets/MajorComponents.png)

### System Event Detector

The system event detector tracks events being triggered on the protocol state contract running on the anchor chain and forwards it to a callback queue with the appropriate routing key depending on the event signature and type among other information.

Related information and other services depending on these can be found in previous sections: [State Transitions](#state-transitions), [Configuration](#configuration).


### Process Hub Core

The Process Hub Core, defined in [`process_hub_core.py`](snapshotter/process_hub_core.py), serves as the primary process manager in the snapshotter.
* Operated by the CLI tool [`processhub_cmd.py`](snapshotter/processhub_cmd.py), it is responsible for starting and managing the `SystemEventDetector` and `ProcessorDistributor` processes.
* Additionally, it spawns the base snapshot and aggregator workers required for processing tasks from the `powerloom-backend-callback` queue. The number of workers and their configuration path can be adjusted in `config/settings.json`.

### Processor Distributor
The Processor Distributor, defined in [`processor_distributor.py`](snapshotter/processor_distributor.py), is initiated using the `processhub_cmd.py` CLI.

* It loads the preloader, base snapshotting, and aggregator config information from the settings file
* It reads the events forwarded by the event detector to the `f'powerloom-event-detector:{settings.namespace}:{settings.instance_id}'` RabbitMQ queue bound to a topic exchange as configured in `settings.rabbitmq.setup.event_detector.exchange`([code-ref: RabbitMQ exchanges and queue setup in pooler](snapshotter/init_rabbitmq.py))
* It creates and distributes processing messages based on the preloader configuration present in `config/preloader.json`, the project configuration present in `config/projects.json` and `config/aggregator.json`, and the topic pattern used in the routing key received from the topic exchange
  * For [`EpochReleased` events](#epoch-generation), it forwards such messages to base snapshot builders for data source contracts as configured in `config/projects.json` for the current epoch information contained in the event.
    https://github.com/PowerLoom/pooler/blob/d8b7be32ad329e8dcf0a7e5c1b27862894bc990a/snapshotter/processor_distributor.py#L694-L810
  * For [`SnapshotSubmitted` events](#base-snapshot-generation), it forwards such messages to single and multi-project aggregate topic routing keys.
    https://github.com/PowerLoom/pooler/blob/d8b7be32ad329e8dcf0a7e5c1b27862894bc990a/snapshotter/processor_distributor.py#L928-L1042



### RPC Helper

Extracting data from the blockchain state and generating the snapshot can be a complex task. The `RpcHelper`, defined in [`utils/rpc.py`](pooler/utils/rpc.py), has a bunch of helper functions to make this process easier. It handles all the `retry` and `caching` logic so that developers can focus on efficiently building their use cases.


### Core API

This component is one of the most important and allows you to access the finalized protocol state on the smart contract running on the anchor chain. Find it in [`core_api.py`](pooler/core_api.py).

The [pooler-frontend](https://github.com/powerloom/pooler-frontend) that serves the Uniswap v2 dashboards hosted by the PowerLoom foundation on locations like https://uniswapv2.powerloom.io/ is a great example of a frontend specific web application that makes use of this API service.

Among many things, the core API allows you to **access the finalized CID as well as its contents at a given epoch ID for a project**.

The main endpoint implementations can be found as follows:

https://github.com/PowerLoom/pooler/blob/d8b7be32ad329e8dcf0a7e5c1b27862894bc990a/snapshotter/core_api.py#L248-L339

https://github.com/PowerLoom/pooler/blob/d8b7be32ad329e8dcf0a7e5c1b27862894bc990a/snapshotter/core_api.py#L343-L404

The first endpoint in `GET /last_finalized_epoch/{project_id}` returns the last finalized EpochId for a given project ID and the second one is `GET /data/{epoch_id}/{project_id}/` which can be used to return the actual snapshot data for a given EpochId and ProjectId.

These endpoints along with the combination of a bunch of other helper endpoints present in `Core API` can be used to build powerful Dapps and dashboards.

You can observe the way it is [used in `pooler-frontend` repo](https://github.com/PowerLoom/pooler-frontend/blob/361268d27584520450bf33353f7519982d638f8a/src/routes/index.svelte#L85) to fetch the dataset for the aggregate projects of top pairs trade volume and token reserves summary:


```javascript
try {
      response = await axios.get(API_PREFIX+`/data/${epochInfo.epochId}/${top_pairs_7d_project_id}/`);
      console.log('got 7d top pairs', response.data);
      if (response.data) {
        for (let pair of response.data.pairs) {
          pairsData7d[pair.name] = pair;
        }
      } else {
        throw new Error(JSON.stringify(response.data));
      }
    }
    catch (e){
      console.error('7d top pairs', e);
    }
```



## Monitoring and Debugging

Login to the pooler docker container using `docker exec -it deploy-boost-1 bash` (use `docker ps` to verify its presence in the list of running containers) and use the following commands for monitoring and debugging
- To monitor the status of running processes, you simply need to run `pm2 status`.
- To see all logs you can run `pm2 logs`
- To see logs for a specific process you can run `pm2 logs <Process Identifier>`
- To see only error logs you can run `pm2 logs --err`


## For Contributors
We use [pre-commit hooks](https://pre-commit.com/) to ensure our code quality is maintained over time. For this contributors need to do a one-time setup by running the following commands.
* Install the required dependencies using `pip install -r dev-requirements.txt`, this will set up everything needed for pre-commit checks.
* Run `pre-commit install`

Now, whenever you commit anything, it'll automatically check the files you've changed/edited for code quality issues and suggest improvements.

## Case Studies

### 1. Pooler: Case study and extending this implementation

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

#### Extending pooler with a Uniswap v2 data point

In this section, let us take a look at the data composition abilities of Pooler to build on the base snapshot being built that captures information on Uniswap trades.

##### Step 1. Review: Base snapshot extraction logic for trade information

Required reading:
* [Base Snapshot Generation](#base-snapshot-generation) and
* [configuring `config/projects.json`](#configuration)
* [Aggregation and data composition](#aggregation-and-data-composition---snapshot-generation-of-higher-order-data-points-on-base-snapshots)

As you can notice in [`config/projects.example.json`](https://github.com/PowerLoom/snapshotter-configs/blob/f46cc86cd08913014decf7bced128433442c8f84/projects.example.json), each project config needs to have the following components

- `project_type` (unique identifier prefix for the usecase, [used to generate project ID](#base-snapshot-generation))
- `projects` (smart contracts to extract data from, pooler can generate different snapshots from multiple sources as long as the Contract ABI is same)
- `processor` (the actual compuation logic reference, while you can write the logic anywhere, it is recommended to write your implementation in pooler/modules folder)

There's currently no limitation on the number or type of usecases you can build using snapshotter. Just write the Processor class and pooler libraries will take care of the rest.

https://github.com/PowerLoom/pooler/blob/1452c166bef7534568a61b3a2ab0ff94535d7229/config/projects.example.json#L1-L35


If we take a look at the `TradeVolumeProcessor` class present at [`snapshotter/modules/computes/trade_volume.py`](https://github.com/PowerLoom/snapshotter-computes/blob/6fb98b1bbc22be8b5aba8bdc860004d35786f4df/trade_volume.py) it implements the interface of `GenericProcessorSnapshot` defined in [`pooler/utils/callback_helpers.py`](pooler/utils/callback_helpers.py).


There are a couple of important concepts here necessary to write your extraction logic:
* `compute` is the main function where most of the snapshot extraction and generation logic needs to be written. It receives the following inputs:
- `epoch` (current epoch details)
- `redis` (async redis connection)
- `rpc_helper` ([`RpcHelper`](pooler/utils/rpc.py) instance to help with any calls to the data source contract's chain)
 - `snapshot` (the generated snapshot)
 - `address` (contract address to extract data from)
 - `epoch_begin` (epoch begin block)
 - `epoch_end` (epoch end block)

Output format can be anything depending on the usecase requirements. Although it is recommended to use proper [`pydantic`](https://pypi.org/project/pydantic/) models to define the snapshot interface.

The resultant output model in this specific example is `UniswapTradesSnapshot` as defined in the Uniswap v2 specific modules directory: [`utils/models/message_models.py`](https://github.com/PowerLoom/snapshotter-computes/blob/6fb98b1bbc22be8b5aba8bdc860004d35786f4df/utils/models/message_models.py#L47-L54). This encapsulates state information captured by `TradeVolumeProcessor` between the block heights of the epoch: `min_chain_height` and `max_chain_height`.



### 2. Zkevm Quests: A Case Study of Implementation

Phase 2 quests form a crucial part of the Powerloom testnet program, where we leverage Snapshotter Peers to monitor on-chain activities of testnet participants across various chains and protocols. These quests predominantly operate in [Bulk Mode](#bulk-mode) due to their one-time nature and the highly dynamic set of participants involved.

In this particular implementation of the peer, known as 'Snapshotter' in the Powerloom Protocol, we have successfully harnessed its capabilities to provide accurate metrics, verified through consensus, pertaining to fundamental data points. These metrics allow us to determine if and when a quest is completed by a testnet participant.

This case study serves as a testament to the effectiveness and versatility of the Snapshotter Peer in real-world scenarios, highlighting its ability to support complex use cases with precision and reliability.

#### Review: Base snapshots

The snapshot builders can be found under the snapshotter-specific implementation directory: [`snapshotter/modules/computes`](https://github.com/PowerLoom/snapshotter-computes/tree/1e145c7f458ce48b8cd2ac860c2ae4a78fad7ea9). Every snapshot builder must implement the interface of [`GenericProcessorSnapshot`](snapshotter/utils/callback_helpers.py)

https://github.com/PowerLoom/pooler/blob/d8b7be32ad329e8dcf0a7e5c1b27862894bc990a/snapshotter/utils/callback_helpers.py#L179-L197


* `compute()` is the callback where the snapshot extraction and generation logic needs to be written. It receives the following inputs:
  * `epoch` (current epoch details)
  * `redis` (async redis connection)
  * `rpc_helper` ([`RpcHelper`](pooler/utils/rpc.py) instance to help with any calls to the data source contract's chain)
  * `snapshot` (the generated snapshot)
  * `address` (contract address to extract data from)
  * `epoch_begin` (epoch begin block)
  * `epoch_end` (epoch end block)

`compute()` should return an instance of a Pydantic model which is in turn uploaded to IPFS by the payload commit service helper method.

https://github.com/PowerLoom/pooler/blob/d8b7be32ad329e8dcf0a7e5c1b27862894bc990a/snapshotter/utils/generic_worker.py#L179-L191

Looking at the pre-supplied [example configuration of `config/projects.json`](https://github.com/PowerLoom/snapshotter-configs/blob/544f3f3355f0b25b99bac7fe8288cec1a4aea3f3/projects.example.json), we can find the following snapshots being generated

#### `zkevm:bungee_bridge`

Snapshot builder: [snapshotter/modules/computes/bungee_bridge.py](https://github.com/PowerLoom/snapshotter-computes/blob/29199feab449ad0361b5867efcaae9854992966f/bungee_bridge.py)

```javascript
    {
      "project_type": "zkevm:bungee_bridge",
      "projects":[
        ],
      "preload_tasks":[
        "block_transactions"
      ],
      "processor":{
        "module": "snapshotter.modules.boost.bungee_bridge",
        "class_name": "BungeeBridgeProcessor"
      }
    },
```
Its preloader dependency is [`block_transactions`](snapshotter/utils/preloaders/tx_receipts/preloader.py) as seen in the [preloader configuration](#preloading).

The snapshot builder then goes through all preloaded block transactions, filters out, and then generates relevant snapshots for wallet address that received funds from the Bungee Bridge refuel contract during that epoch.

https://github.com/PowerLoom/snapshotter-computes/blob/29199feab449ad0361b5867efcaae9854992966f/bungee_bridge.py#L40-L92

## Find us

* [Discord](https://powerloom.io/discord)
* [Twitter](https://twitter.com/PowerLoomHQ)
* [Github](https://github.com/PowerLoom)
* [Careers](https://wellfound.com/company/powerloom/jobs)
* [Blog](https://blog.powerloom.io/)
* [Medium Engineering Blog](https://medium.com/powerloom)
