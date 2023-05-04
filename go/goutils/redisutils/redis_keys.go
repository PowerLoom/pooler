package redisutils

const REDIS_KEY_STORED_PROJECTS string = "storedProjectIds"
const REDIS_KEY_PROJECT_PAYLOAD_CIDS string = "projectID:%s:payloadCids"
const REDIS_KEY_PROJECT_CIDS string = "projectID:%s:Cids"
const REDIS_KEY_PROJECT_FINALIZED_HEIGHT string = "projectID:%s:blockHeight"
const REDIS_KEY_PRUNING_CYCLE_DETAILS string = "pruningRunStatus"

const REDIS_KEY_PRUNING_CYCLE_PROJECT_DETAILS string = "pruningProjectDetails:%s"

const REDIS_KEY_PRUNING_STATUS string = "projects:pruningStatus"
const REDIS_KEY_PROJECT_METADATA string = "projectID:%s:dagSegments"

const REDIS_KEY_PROJECT_TAIL_INDEX string = "projectID:%s:slidingCache:%s:tail"
const REDIS_KEY_PRUNING_VERIFICATION_STATUS string = "projects:pruningVerificationStatus"

const REDIS_KEY_PROJECT_EPOCH_SIZE string = "projectID:%s:epochSize"
const REDIS_KEY_PROJECT_FIRST_EPOCH_END_HEIGHT string = "projectID:%s:firstEpochEndHeight"

const REDIS_KEY_PROJECT_PENDING_TXNS = "projectID:%s:pendingTransactions"
const REDIS_KEY_PROJECT_TENTATIVE_BLOCK_HEIGHT = "projectID:%s:tentativeBlockHeight"
const REDIS_KEY_PROJECT_BLOCK_HEIGHT string = "projectID:%s:blockHeight"
const REDIS_KEY_TOKEN_PAIR_CONTRACT_TOKENS_DATA string = "uniswap:pairContract:%s:%s:PairContractTokensData"
const REDIS_KEY_TOKEN_PRICE_HISTORY string = "uniswap:tokenInfo:%s:%s:priceHistory"
const REDIS_KEY_PAIR_TOKEN_ADDRESSES string = "uniswap:pairContract:%s:%s:PairContractTokensAddresses"
const REDIS_KEY_TOKEN_BLOCK_HEIGHT_PRICE string = "uniswap:pairContract:%s:%s:cachedPairBlockHeightTokenPrice"
const REDIS_KEY_TOKENS_SUMMARY_SNAPSHOTS_ZSET string = "uniswap:V2TokensSummarySnapshot:%s:snapshotsZset"
const REDIS_KEY_PAIRS_SUMMARY_SNAPSHOTS_ZSET string = "uniswap:V2PairsSummarySnapshot:%s:snapshotsZset"
const REDIS_KEY_DAILY_STATS_SUMMARY_SNAPSHOTS_ZSET string = "uniswap:V2DailyStatsSnapshot:%s:snapshotsZset"
const REDIS_KEY_TOKENS_SUMMARY_SNAPSHOT_AT_BLOCKHEIGHT string = "uniswap:V2TokensSummarySnapshot:%s:%d"
const REDIS_KEY_PAIRS_SUMMARY_SNAPSHOT_BLOCKHEIGHT string = "uniswap:V2PairsSummarySnapshot:%s:snapshot:%d"
const REDIS_KEY_TOKENS_SUMMARY_TENTATIVE_HEIGHT string = "projectID:uniswap_V2TokensSummarySnapshot_%s:tentativeBlockHeight"

const REDIS_KEY_DAG_VERIFICATION_STATUS string = "projectID:%s:dagVerificationStatus"
const REDIS_KEY_LAST_REPORTED_DAG_HEIGHT string = "projectID:%s:lastReportedHeight"
const REDIS_KEY_PROJECTS_INDEX_STATUS string = "projects:IndexStatus"
const REDIS_KEY_PROJECT_DAG_CHAIN_GAPS string = "projectID:%s:dagChainGaps"
const REDIS_KEY_PRUNING_ISSUES string = "%s:pruningIssues"
const REDIS_KEY_ISSUES_REPORTED string = "monitoring:issueReports"
const REDIS_KEY_FINALIZED_INDEX_PAYLOAD string = "projects:%s:finalizedIndexPayload"
