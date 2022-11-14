# Fpmm-pooler-internal / snapshotter

<!-- TABLE OF CONTENTS -->
## Table of Contents
* [Epoch Generation](#epochGeneration)
  * [Epoch Size](#epochGeneration)
  * [System Linear Ticker](#systemLinearTicker)
  * [Epoch Finalizer and Collator](#epochFinalizerCollator)
* [Snapshot Building](#snapshotBuilding)
  * [Liquidity / Pair Reserves](#snapshotBuilding)
  * [Fetch event logs](#fetchEventLogs)
  * [Pair trade volume](#pairTradeVolume)
  * [Token Price in USD](#tokenPriceUSD)
  * [Rate Limiter](#rateLimiter)
  * [Batching RPC calls & caching data](#batchAndCache)
</br>
</br>


## Epoch Generation <i id="epochGeneration"></i>
An epoch denotes a range of block heights on the data source blockchain, Ethereum mainnet in the case of Uniswap-v2. This makes it easier to collect state transitions and snapshots of data on equally spaced block height intervals ([Whitepaper-reference](https://powerloom.notion.site/PowerLoom-Protocol-Overview-c3bf9dd9323541118d46a4d8684565d1#12204d5cc5e9459bb13b0c4512d6cefc)).

### Epoch size
<b>Epoch size</b> is configurable using the `settings.json` config file, [code-ref](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/settings.example.json#L106-L110):
```
"epoch": {
    "height": 10, // Epoch size
    "head_offset": 2, // Epoch Offset
    "block_time": 2 // Average block generation time
},
```
* `height`: represent the range of blocks on the source blockchain, combined called epoch size.
* `head_offset`: a configurable ‘offset’ from the bleeding edge of the chain.
* `block_time`: average time taken to generate a new block on the source chain.

### System Linear Ticker <i id="systemLinearTicker"></i>
<b>System Ticker Linear Module ([code-ref](https://github.com/PowerLoom/fpmm-pooler-internal/blob/main/system_ticker_linear.py))</b>: 
This service keeps track of the head of the chain as it moves ahead, while starting the service we can pass the block number as head to generate snapshots from older heights([ref](https://www.notion.so/powerloom/Setup-and-Procedures-for-Pooler-Audit-Protocol-dbe612da8c94454d81f4de49b815f24d#bb059867909d46c4a832794ea4e3f11e)).   
```
cur_block = latest_source_block / passed_argument
end_block = cur_block - HEAD_OFFSET
if (end_block - begin_block + 1) >= EPOCH_SIZE:
    // broadcast epoch to distributor and workers
else:
    // wait for more blocks 
```
Once the head of the chain has moved sufficiently ahead so that an epoch can be published, epoch finalization and epoch collator broadcast the epoch to the distributor([ref](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/system_ticker_linear.py#L107)).

### Epoch Finalizer and Collator <i id="epochFinalizerCollator"></i>
Currently, it's a very minimal wrapper, where we take the epoch and set a unique broadcast ID against it to track it further across workers.
```
// Broadcasted Message
{
    "begin": int,
    "end": int,
    "broadcast_id": uuid,
    "contracts": [string],
    "reorg": bool (Optional)
}
```
Once the broadcast message is ready we queue it on rabbitMQ to be processed by the distributor and workers, references: 
* [Finalizer](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/system_epoch_finalizer.py#L70)
* [Epoch Collator](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/system_epoch_collator.py#L124-L140)


</br>
</br>


## Snapshot Building <i id="snapshotBuilding"></i>
Once an epoch is published, an array of workers kick in that collect important state information and event logs on the pair contracts against the block height range specified.
Get familiar with the terms & concepts of this section in the [Glossary](https://powerloom.notion.site/PowerLoom-Protocol-Overview-c3bf9dd9323541118d46a4d8684565d1#29286f22a85640c9bedeeefb99eb49f3).


> We track liquidity and trade volume for every pair contract separately, which means a separate DAG snapshot chain is generated for each of them.

</br>


### Liquidity / Pair Reserves
Reserves of each token in pair contract, uniswap pair contract interface has a function called `getReserves()` to get reserves of pair. `uniswap_functions.py` module has a core function to calculate liquidity `get_pair_reserves`([code-ref](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/uniswap_functions.py#L809-L816)).

Steps to calculate liquidity:
* we start with fetching block details to get the timestamp of each block
* read/fetch pair metadata
* fetch token prices
* fetch pair reserves for each token
* using all these data points prepare snapshots
```
async def get_pair_reserves(
    ...
    pair_address, 
    from_block, to_block,
    ...
):
    ...
    ...
    return {
        'token0': token0Amount,
        'token1': token1Amount,
        'token0USD': token0USD,
        'token1USD': token1USD,
        'timestamp': timestamp
    }
```

</br>
</br>


### Fetch event logs <i id="fetchEventLogs"></i>
Trade volume is derived by summing values of swap events against a pair contract. We fetch event logs against an epoch’s block range by supplying respective event signatures(e.g. [Uniswap v2 events](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/uniswap_functions.py#L91-L95)). Ethereum JSON RPC has a method to get event logs in a given block range: [eth_getLogs](https://ethereum.org/en/developers/docs/apis/json-rpc/#eth_getlogs).


`rpc_helper.py` module contains a helper to fetch and parse event logs ([code-ref](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/rpc_helper.py#L372)):
```
web3Provider.eth.get_logs({
    'address': Web3.toChecksumAddress(contract_address),
    'toBlock': toBlock,
    'fromBlock': fromBlock,
    'topics': topics
})
```

</br>
</br>


### Pair trade volume <i id="pairTradeVolume"></i>
Trade volume is defined as the number of tokens swapped in and out of a pair contract. `uniswap_functions.py` module contains a function called `get_pair_trade_volume` to calculate trade volume ([code-ref](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/uniswap_functions.py#L1038)).   

`Trade Volume = SwapValueUSD = token0Amount * token0PriceUSD = token1Amount * token1PriceUSD`

Steps to calculate trade volume:
* we start with fetching block details to get the timestamp of each block
* read/fetch pair metadata
* fetch token prices
* fetch event logs of pair-contract
* group all logs by mint, burn and swap
* add swap amount in USD as trade volume
```
async def get_pair_trade_volume(
    ...
    pair_address, 
    from_block, to_block,
    ...
):
    ...
    ...
    return UniswapTradeEvent 
```
`UniswapTradeEvent`: return type [data-model](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/message_models.py#L62)


</br>
</br>


### Token Price in USD <i id="tokenPriceUSD"></i>  
USD price of the token is used to calculate pair liquidity and trade volume snapshot. By USD price we mean a token price in terms of stable coins like DAI, USDC and USDT!


`uniswap_functions.py` module contains a function called `get_token_price_in_block_range`([ref](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/uniswap_functions.py#L612)) to calculate the token USD price.   
Steps to calculate the token price:
* fetch Eth USD price ([ref](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/uniswap_functions.py#L376))
* if `token == ETH` then return Eth USD price
* else find a pair with whitelisted tokens([ref](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/settings.example.json#L27))
* find the derived Eth of the token using found pair ([ref](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/uniswap_functions.py#L559))
* put everything in the below formula to calculate the price

Important formulas to calculate tokens price in USD:
* `EthPriceUSD = StableCoinReserves / EthReserves`
* `TokenPriceUSD = EthPriceUSD * tokenDerivedEth`

> Note: there is threshold liquidity for each pair, if liquidity is lower than threshold then we find a pair with another whitelisted token


</br>
</br>


### Rate Limiter <i id="rateLimiter"></i>
Every RPC call honors a configured rate limit on the Ethereum client node. The rate limiter is essentially built on a couple of LUA scripts that atomically increase hit counts against timestamp windowed Redis keys with appropriate expiry. The rate limiter library helpers raise a specific exception if limits are exceeded. These rate limit boundaries are configured against an RPC endpoint by a string that is structured like `100000000/day;20000/minute;2500/second`.

The rate limiter is written in a module called `rate_limiter.py`:
* [rate limiter module](https://github.com/PowerLoom/fpmm-pooler-internal/blob/main/rate_limiter.py)
* [RPC rate limit helper function](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/rate_limiter.py#L64)

```
rate_limiter:
    1. init_rate_limiter #// get limits from settings configuration, load lua script on redis, etc..
    2. verify if we have quota for another request ?

    if can_request:
        3.enjoy_rpc!
    else:
        4. panic! rate limit exhaust error
```


</br>
</br>


### Batching RPC calls & caching data <i id="batchAndCache"></i>
We are making repeating RPC calls for the same data at many points in the codebase e.g. token price in liquidity as well as in trade volume. To optimize this we have caching layer in individual functions e.g. [Eth USD price](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/uniswap_functions.py#L390-L399).
On the other hand, we batch RPC calls as much as possible using the batching technique explained in [Geth docs](https://geth.ethereum.org/docs/rpc/batch).

All RPC batch calls function/helper are residing in a module called `rpc_helper.py` ([ref](https://github.com/PowerLoom/fpmm-pooler-internal/blob/main/rpc_helper.py)).

> There is on-going sprint around pooler-modularization caching layer and RPC calls, which will probably make this section outdated. ([related-issue](https://github.com/PowerLoom/fpmm-pooler-internal/issues/118))