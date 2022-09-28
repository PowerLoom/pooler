package main

const REDIS_KEY_TOKEN_PAIR_CONTRACT_TOKENS_DATA = "uniswap:pairContract:%s:%s:PairContractTokensData"
const REDIS_KEY_TOKEN_PRICE_HISTORY = "uniswap:tokenInfo:%s:%s:priceHistory"
const REDIS_KEY_PAIR_TOKEN_ADDRESSES = "uniswap:pairContract:%s:%s:PairContractTokensAddresses"
const REDIS_KEY_TOKEN_BLOCK_HEIGHT_PRICE = "uniswap:pairContract:%s:%s:cachedPairBlockHeightTokenPrice"
const REDIS_KEY_TOKENS_SUMMARY_SNAPSHOTS_ZSET = "uniswap:V2TokensSummarySnapshot:%s:snapshotsZset"
const REDIS_KEY_AGGREGATORS_SNAPSHOTS_ZSET = "uniswap:%s:%s:snapshotsZset"
const REDIS_KEY_TOKENS_SUMMARY_SNAPSHOT_AT_BLOCKHEIGHT = "uniswap:V2TokensSummarySnapshot:%s:%d"
const REDIS_KEY_PAIRS_SUMMARY_SNAPSHOTS_ZSET = "uniswap:V2PairsSummarySnapshot:%s:snapshotsZset"
const REDIS_KEY_PAIRS_SUMMARY_SNAPSHOT_BLOCKHEIGHT = "uniswap:V2PairsSummarySnapshot:%s:snapshot:%d"
const REDIS_KEY_TOKENS_SUMMARY_TENTATIVE_HEIGHT = "projectID:uniswap_V2TokensSummarySnapshot_%s:tentativeBlockHeight"
