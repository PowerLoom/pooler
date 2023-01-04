
## Table of Contents

- [Table of Contents](#table-of-contents)
- [Overview](#overview)
- [Requirements](#requirements)
- [Setup Instructions](#setup-instructions)
  - [Setup Virtual Env](#setup-virtual-env)
  - [Generate settings.json](#generate-settingsjson)
    - [Required](#required)
    - [Optional](#optional)
  - [Populate `static/cached_pair_addresses.json`](#populate-staticcached_pair_addressesjson)
  - [Set up Env variables](#set-up-env-variables)
- [Starting all Processes](#starting-all-processes)
- [Monitoring and Debugging](#monitoring-and-debugging)
- [Epoch Generation](#epoch-generation)
- [Snapshot Building](#snapshot-building)
  - [Token Price in USD](#token-price-in-usd)
  - [Pair Metadata](#pair-metadata)
  - [Liquidity / Pair Reserves](#liquidity--pair-reserves)
  - [Fetch event logs](#fetch-event-logs)
  - [Pair trade volume](#pair-trade-volume)
  - [Rate Limiter](#rate-limiter)
  - [Batching RPC calls](#batching-rpc-calls)
- [Architecture Details](#architecture-details)


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


This specific implementation is called Pooler since it tracks Uniswap v2 'pools'.

Together with an Audit Protocol instance, they form a recently released PoC whose objectives were

- to present a fully functional, distributed system comprised of lightweight services that can be deployed over multiple instances on a network or even on a single instance
- to be able to serve the most frequently sought data points on Uniswap v2
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

## Requirements

* macOS or Linux (We're still working on windows support)
* Python 3.8 or above
* [Redis](https://redis.io/docs/getting-started/installation/)
* [RabbitMQ](https://www.rabbitmq.com/download.html)
* [Pm2](https://pm2.keymetrics.io/docs/usage/quick-start/)
* [Poetry](https://python-poetry.org/docs/)
## Setup Instructions

### Setup Virtual Env
Make sure you have poetry installed and run `poetry install`.

### Generate settings.json
Pooler needs `settings.json` to be present in your project root directory. We've provided a settings template in `settings.example.json` to help you get started.

Copy over [`settings.example.json`](settings.example.json) to `settings.json` using

```
cp settings.example.json settings.json
```

Now, there's a lot of configuration in `settings.json` but to get started, you just need to focus on a couple of sections.

Here are the steps you need to get started with `settings.json`.
#### Required
- Signup at [Powerloom Dashboard](https://ethindia22.powerloom.io) and generate your API key.
- Add your generated API Key in the `namespace` section
- Fill the hosted audit protocol endpoint in the `audit_protocol_engine.url` key or you can use `https://auditprotocol-ethindia.powerloom.io/`

#### Optional
- We've provided the `ipfs_url` by default but if you want to run your own IPFS node, you  can add that URL here
- RabbitMq and Redis should work out of the box with the default config but if it doesn't, you can update the config in `rabbitmq` and `redis` keys respectively.
- Update the `host` and `port` keys if you want to run the service on some other port
### Populate `static/cached_pair_addresses.json`

Copy over [`static/cached_pair_addresses.example.json`](static/cached_pair_addresses.example.json) to `static/cached_pair_addresses.json`

```
cp static/cached_pair_addresses.example.json static/cached_pair_addresses.json
```

These are the pair contracts on Uniswap v2 or other forks of it that will be tracked for the following in this example implementation.

* Token reserves of `token0` and `token1`
* Trade volume information as described in the [Overview](#overview) section.

## Starting all Processes
To launch all the required processes, you can run
```commandline
pm2 start pm2.config.js
```
then you need to execute `init_processes.sh` using the following command
```commandline
./init_processes.sh
```

## Monitoring and Debugging
- To monitor the status of running processes, you simply need to run `pm2 status`.
- To see all logs you can run `pm2 logs`
- To see logs for a specific process you can run `pm2 logs <Process Identifier>`
- To see only error logs you can run `pm2 logs --err`

## For Contributors
We use [pre-commit hooks](https://pre-commit.com/) to ensure our code quality is maintained over time. For this contributors need to do a one-time setup by running the following commands.
* Install the required dependencies using `pip install dev-requirements.txt`, this will setup everything needed for pre-commit checks.
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


## Snapshot Building

Overview of broadcasted epoch processing, building snapshot, and submitting it to audit-protocol ([whitepaper-ref](https://www.notion.so/powerloom/PowerLoom-Protocol-Overview-c3bf9dd9323541118d46a4d8684565d1#8ad76b8362b341bcaa9b3ae9fe203271)):

1. Published/broadcasted epochs are received by `PairTotalReservesProcessorDistributor`, and get distributed to callback workers by publishing messages on respective queues ([code-ref](pooler/callback_modules/pair_total_reserves.py#L480-L538)).
[Distributor code-module](pooler/callback_modules/pair_total_reserves.py#L547-L660)
```
queue.enqueue_msg_delivery(
    exchange=f'pair_processor_exchange',
    routing_key='callback_routing_key',
    msg_body={epoch_begin, epoch_end, pair_contract, broadcast_id}
)
```

2. The Distributor's messages are received by the `PairTotalReservesProcessor` on_message handler. Multiple workers are running parallelly consuming incoming messages ([code-ref](pooler/callback_modules/pair_total_reserves.py#L312-L332)).
[Processor code-module](pooler/callback_modules/pair_total_reserves.py#L56-L545)


3. Each message goes through capturing smart-contract data and transforming it into a standardized JSON schema. All these data-point operations are detailed in the next section.

4. Generated snapshots get submitted to audit-protocol with appropriate status updated against message broadcast_id ([code-ref](pooler/callback_modules/pair_total_reserves.py#L354-L479)).
```
await AuditProtocolCommandsHelper.commit_payload(
    pair_contract_address=epoch_snapshot.contract, stream='pair_total_reserves',
    report_payload=payload, ...
)
```


Implementation breakdown of all <u><b>snapshot data-point operations</b></u> to transform smart-contract data and generate snapshots for each epoch. For more explanation check out the [whitepaper section](https://www.notion.so/powerloom/PowerLoom-Protocol-Overview-c3bf9dd9323541118d46a4d8684565d1#8ad76b8362b341bcaa9b3ae9fe203271):



### Token Price in USD

Token price in USD(stable coins) more details in [whitepaper](https://www.notion.so/powerloom/PowerLoom-Protocol-Overview-c3bf9dd9323541118d46a4d8684565d1#8bb48365ac444f22b2376433b5cf36f7).

Steps to calculate the token price:
1. Calculate Eth USD price ([code-ref](pooler/callback_modules/uniswap/pricing.py#L345-L348))
```
eth_price_dict = await get_eth_price_usd(from_block, to_block, web3_provider, ...)
```
`get_eth_price_usd()` function calculates the average eth price using stablecoin pools (USDC, USDT, and DAI) ( [code-ref](pooler/callback_modules/uniswap/pricing.py#L27-L185) ):

[[whitepaper-ref](https://www.notion.so/powerloom/PowerLoom-Protocol-Overview-c3bf9dd9323541118d46a4d8684565d1#10e57df8515d4d77bf9ac97c09e6f5db)]
```
Eth_Price_Usd = daiWeight * dai_price + usdcWeight * usdc_price + usdtWeight * usdt_price
```

2. Find a pair of target tokens with whitelisted tokens ([code-ref](pooler/callback_modules/uniswap/pricing.py#L352-L402)):
```
for -> (settings.UNISWAP_V2_WHITELIST):
    pair_address = await get_pair(white_token, token_adress, ...)
    if pair_address != "0x0000000000000000000000000000000000000000":
        //process...
        break
```
`get_pair()` function returns a pair address given token addresses, more detail in [Uniswap doc](https://docs.uniswap.org/protocol/V2/reference/smart-contracts/factory#getpair).

3. Calculate the derived Eth of the target token using the whitelist pair([code-ref](pooler/callback_modules/uniswap/pricing.py#L374-L377)):
```
white_token_derived_eth_dict = await get_token_derived_eth(
    from_block, to_block, white_token_metadata, web3_provider, ...
)
```
`get_token_derived_eth()` function return the derived ETH amount of the given token([code-ref](pooler/callback_modules/uniswap/pricing.py#L252-L308)):
```
token_derived_eth_list = batch_eth_call_on_block_range(
    'getAmountsOut', UNISWAP_V2_ROUTER, from_block, to_block=to_block,
    params=[10, [whitelist_token_address, weth_address]], ...
)
```
`getAmountsOut()` is a uniswap-router2 smart contract function, more details in [Uniswap-doc](https://docs.uniswap.org/protocol/V2/reference/smart-contracts/router-02#getamountsin).


4. Check if the Eth reserve of the whitelisted token is more than the threshold, else repeat steps 2 and 3 ([code-ref](pooler/callback_modules/uniswap/pricing.py#L386-L389)):
```
...
if white_token_reserves < threshold:
    continue
else:
    for ->(from_block, to_block):
        token_price_dict[block] = token_eth_price[block] * eth_usd_price[block]
```

Important formulas to calculate tokens price

[whitepaper-ref](https://www.notion.so/powerloom/PowerLoom-Protocol-Overview-c3bf9dd9323541118d46a4d8684565d1#8bb48365ac444f22b2376433b5cf36f7)

* `EthPriceUSD = StableCoinReserves / EthReserves`
* `TokenPriceUSD = EthPriceUSD * tokenDerivedEth`



### Pair Metadata


Fetch the `symbol`, `name`, and `decimal` of a given pair from RPC and store them in the cache.

1. check if cache exists, metadata cache is stored as a Redis-hashmap ([code-ref](pooler/callback_modules/uniswap/helpers.py#L93-L97)):
```
pair_token_addresses_cache, pair_tokens_data_cache = await asyncio.gather(
    redis_conn.hgetall(uniswap_pair_contract_tokens_addresses.format(pair_address)),
    redis_conn.hgetall(uniswap_pair_contract_tokens_data.format(pair_address))
)
```

2. fetch metadata from pair smart contract ([code-ref](pooler/callback_modules/uniswap/helpers.py#L110-L125)):
```
web3_provider.batch_call([
    token0-> name, symbol, decimals,
    token1-> name, symbol, decimals,
])
```

3. store cache and return prepared metadata, return metadata ([core-ref](pooler/callback_modules/uniswap/helpers.py#L146-L228)).


### Liquidity / Pair Reserves
[code-ref](uniswap_functions.py#L809-L816)
Reserves of each token in pair contract ([more details in whitepaper](https://www.notion.so/powerloom/PowerLoom-Protocol-Overview-c3bf9dd9323541118d46a4d8684565d1#e04df592d3034f18aa1fc9502f749ec9)):

Steps to calculate liquidity:
1. Fetch block details from RPC and return `{block->details}` dictionary ([code-ref](uniswap_functions.py#L824-L834)):
```
block_details_dict = await get_block_details_in_block_range(
    from_block, to_block, web3_provider, ...
)
```
`get_block_details_in_block_range()` is a batch RPC call to fetch data of each block for a given range ([code-ref](uniswap_functions.py#L726-L732)).

2. Fetch pair metadata of the pair smart contract e.g. symbol, decimal, etc ([code-ref](uniswap_functions.py#L836-L839)):
`get_pair_metadata()` invoke `symbol()`, `decimal()` and `name()` functions on the pair's smart contract, more details in the [metadata section](#pairMetadata).
```
pair_per_token_metadata = await get_pair_metadata(
    pair_address, ...
)
```

3. Calculate the pair's token price ([code-ref](uniswap_functions.py#L843-L852)):
```
token0_price_map = await get_token_price_in_block_range(token0, from_block, to_block, ...)
token1_price_map = await get_token_price_in_block_range(token1, from_block, to_block, ...)
```
`get_token_price_in_block_range()` returns `{block->price}` dictionary for a given token, more details in the [price section](#tokenPriceUSD).

4. Fetch pair reserves for each token ([code-ref](uniswap_functions.py#L865-L872)):
```
reserves_array = batch_eth_call_on_block_range(
    web3_provider, abi_dict, 'getReserves',
    pair_address, from_block, to_block, ...
)
```
`reserves_array` is an array array, each element containing:`[token0Reserves, token1Reserves, timestamp]`. It invokes the `getReserves()` function on pair contracts, more details on [Uniswap-docs](https://docs.uniswap.org/protocol/V2/reference/smart-contracts/pair#getreserves).

5. Prepare the final liquidity snapshot, by iterating on each block and taking a product of `tokenReserve` and `tokenPrice` ([code-ref](uniswap_functions.py#L878-L897)):

6. `get_pair_reserve()` return type [data-model](uniswap_functions.py#L890-L896).



### Fetch event logs
[code-ref](uniswap_functions.py#L1081-L1091)
Fetch event logs to calculate trade volume using `eth_getLogs`, more details in [whitepaper](https://www.notion.so/powerloom/PowerLoom-Protocol-Overview-c3bf9dd9323541118d46a4d8684565d1#b42d180a965d4fb9888fb2a586bdd0de).


```
# fetch logs for swap, mint & burn
event_sig, event_abi = get_event_sig_and_abi(UNISWAP_TRADE_EVENT_SIGS, UNISWAP_EVENTS_ABI)
get_events_logs, **{
    'contract_address': pair_address, 'topics': [event_sig], 'event_abi': event_abi, ...
}
```
`get_events_logs()` function is written in `rpc_helpers.py` module. It uses the `eth.get_logs` RPC function to fetch event logs of given topics in block range ([code-ref](pooler/utils/rpc_helper.py#L372-L387)):
```
event_log = web3Provider.eth.get_logs({
    'address': contract_address, 'toBlock': toBlock,
    'fromBlock': fromBlock, 'topics': topics
})
for -> (event_log):
    evt = get_event_data(ABICodec, abi, log)
```
`ABICodec` is used to decode the event logs in plain text using the `get_event_data` function, check out more details in the [library](https://github.com/ethereum/web3.py/blob/fbaf1ad11b0c7fac09ba34baff2c256cffe0a148/web3/_utils/events.py#L200).


### Pair trade volume
Calculate The Trade volume of a pair using event logs, more details in [whitepaper](https://www.notion.so/powerloom/PowerLoom-Protocol-Overview-c3bf9dd9323541118d46a4d8684565d1#be2e5c71701d4491a04572589ac67f1b).

`Trade Volume = SwapValueUSD = token0Amount * token0PriceUSD = token1Amount * token1PriceUSD`

Steps to calculate trade volume:
1. Fetch block details from RPC and return `{block->details}` dictionary ([code-ref](pooler/callback_modules/uniswap/core.py#L292-L296)):
```
block_details_dict = await get_block_details_in_block_range(
    from_block, to_block, web3_provider, ...
)
```
`get_block_details_in_block_range()` is a batch RPC call to fetch data of each block for a given range ([code-ref](pooler/callback_modules/uniswap/helpers.py#L238-L321)).

2. Fetch pair metadata of the pair smart contract e.g. symbol, decimal, etc ([code-ref](pooler/callback_modules/uniswap/core.py#L303-L308)):
`get_pair_metadata()` invoke `symbol()`, `decimal()` and `name()` functions on the pair's smart contract, more details in the [metadata section](#pairMetadata).
```
pair_per_token_metadata = await get_pair_metadata(
    pair_address, ...
)
```

3. Calculate the pair's token price ([code-ref](pooler/callback_modules/uniswap/core.py#L309-L322)):
```
token0_price_map = await get_token_price_in_block_range(token0, from_block, to_block, ...)
token1_price_map = await get_token_price_in_block_range(token1, from_block, to_block, ...)
```

`get_token_price_in_block_range()` returns `{block->price}` dictionary for a given token, more details in the [price section](#tokenPriceUSD).


4. Fetch event logs in the given block range, following the [event log section](#fetchEventLogs).

5. Group logs by transaction hash ([code-ref](pooler/callback_modules/uniswap/core.py#L349-L350))
```
for -> (event_logs):
    transaction_dict[tx_hash].append(log)
```

6. Iterate on grouped logs, and group again by event type(swap, mint and burn) ([code-ref](pooler/callback_modules/uniswap/core.py#L405-L444))

7. Add swap logs amount as effective trade volume ([code-ref](pooler/callback_modules/uniswap/core.py#L432-L435))

8. `get_pair_trade_volume()` return type [data-model](pooler/utils/models/message_models.py#L62)



### Rate Limiter
[code-ref](pooler/utils/redis/rate_limiter.py#L64)
All RPC nodes specified in [settings.json](settings.example.json#L60-L75) has a rate limit to them, every RPC calls honor this limit ([more details](https://www.notion.so/powerloom/PowerLoom-Protocol-Overview-c3bf9dd9323541118d46a4d8684565d1#d9bef53da81449b7b5e39290b25843ac)).


* [Rate limiter module](pooler/utils/redis/rate_limiter.py)
* [helper function](pooler/utils/redis/rate_limiter.py#L64)

```
rate_limiter:
    1. init_rate_limiter #// get limits from settings configuration, load Lua script on Redis, etc.
    2. verify if we have a quota for another request?
    if can_request:
        3.enjoy_rpc!
    else:
        4. panic! rate limit exhaust error
```



### Batching RPC calls

Batch RPC calls by sending multiple queries in a single request, details in [Geth docs](https://geth.ethereum.org/docs/rpc/batch).
```
[
    { id: unique_id, method: eth_function, params: params, jsonrpc: '2.0' },
    ...
]
```

`rpc_helper.py` ([code-ref](pooler/utils/rpc_helper.py)) module contains several helpers which use batching:
* [batch_eth_call_on_block_range](pooler/utils/rpc_helper.py#L268): to query a contract function on multiple block-heights.
* [batch_eth_get_block](pooler/utils/rpc_helper.py#L330): to get block data at multiple block heights.

## Architecture Details
Details about working of various components is present in [Details.md](pooler/Details.md) if you're interested to know more about Pooler.
