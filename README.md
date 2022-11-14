# Fpmm-pooler-internal / snapshotter

<!-- TABLE OF CONTENTS -->
## Table of Contents
* [Epoch Generation](#epochGeneration)
  * [Epoch Size](#epochGeneration)
  * [System Linear Ticker](#systemLinearTicker)
  * [Epoch Finalizer and Collator](#epochFinalizerCollator)
* [Snapshot Building](#snapshotBuilding)
</br>
</br>


## Epoch Generation <i id="epochGeneration"></i>
An epoch denotes a range of block heights on the data source blockchain, Ethereum mainnet in the case of Uniswap-v2. This makes it easier to collect state transitions and snapshots of data on equally spaced block height intervals.

### Epoch size
<b>Epoch size</b> is configurable using `settings.json` config file, [code-ref](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/settings.example.json#L106-L110):
```
"epoch": {
    "height": 10, // Epoch size
    "head_offset": 2, // Epoch Offset
    "block_time": 2 // Average block generation time
},
```
* `height`: represent range of blocks on source blockchain, combined called epoch size.
* `head_offset`: a configurable ‘offset’ from the bleeding edge of the chain.
* `block_time`: average time taken to generate a new block on source chain.

### System Linear Ticker <i id="systemLinearTicker"></i>
<b>System Ticker Linear Module ([code-ref](https://github.com/PowerLoom/fpmm-pooler-internal/blob/main/system_ticker_linear.py))</b>: 
This service keeps track of the head of the chain as it move ahead, while starting the service we can pass block number as head to generate snapshots from older heights([ref](https://www.notion.so/powerloom/Setup-and-Procedures-for-Pooler-Audit-Protocol-dbe612da8c94454d81f4de49b815f24d#bb059867909d46c4a832794ea4e3f11e)).   
```
cur_block = latest_source_block / passed_argument
end_block = cur_block - HEAD_OFFSET
if (end_block - begin_block + 1) >= EPOCH_SIZE:
    // broadcast epoch to distributor and workers
else:
    // wait for more blocks 
```
Once the head of the chain has moved sufficiently ahead so that an epoch can be published, epoch finalization and epoch collator broadcast the epoch to distributor([ref](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/system_ticker_linear.py#L107)).

### Epoch Finalizer and Collator <i id="epochFinalizerCollator"></i>
Currently it's a very minilmal wrapper, where we take the epoch and set a unique broadcast ID against it to track it further across workers.
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
Once broadcast message is ready we queue it on rabbitMQ to be processed by distributor and workers, references: 
* [Finalizer](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/system_epoch_finalizer.py#L70)
* [Epoch Collator](https://github.com/PowerLoom/fpmm-pooler-internal/blob/a9214a55922cbdee00f8e260eb9d960620fbcaff/system_epoch_collator.py#L124-L140)


</br>
</br>


## Snapshot Building <i id="snapshotBuilding"></i>