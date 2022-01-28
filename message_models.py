from pydantic import BaseModel, validator
from typing import Union, List, Optional, Mapping

# TODO: clean up polymarket specific models as we develop the callback workers


class EpochBase(BaseModel):
    begin: int
    end: int


class EpochBroadcast(EpochBase):
    broadcast_id: str


class EpochConsensusReport(EpochBase):
    reorg: bool = False


class SystemEpochStatusReport(EpochBase):
    broadcast_id: str
    reorg: bool = False


class PowerloomCallbackEpoch(SystemEpochStatusReport):
    contracts: List[str]


class PowerloomCallbackProcessMessage(SystemEpochStatusReport):
    contract: str


class RPCNodesObject(BaseModel):
    NODES: List[str]
    RETRY_LIMIT: int


class ProcessHubCommand(BaseModel):
    command: str
    pid: Optional[int] = None
    proc_str_id: Optional[str] = None
    init_kwargs: Optional[dict] = dict()


class PolymarketTradeVolumeBase(BaseModel):
    contract: str
    tradeVolume: float
    chainHeight: int
    timestamp: float


class PolymarketSeedTradeVolumeRequest(BaseModel):
    contract: str
    chainHeight: int


class PolymarketBuySharesEvent(BaseModel):
    investmentAmount: int
    feeAmount: int
    outcomeTokensBought: int
    buyer: str
    outcomeIndex: int


class PolymarketSellSharesEvent(BaseModel):
    returnAmount: int
    feeAmount: int
    outcomeTokensSold: int
    seller: str
    outcomeIndex: int


class PolymarketBuyShareTransaction(BaseModel):
    """{
        "event_data": {
            "investmentAmount": 15000000,
            "feeAmount": 300000,
            "outcomeTokensBought": 15045242,
            "buyer": "0x5d6553353d6f0767b5bcafd957ffea38e60c260e",
            "outcomeIndex": 1
        },
        "txHash": "0x05af72cf36e531324221c623219485ae39efd94ce6f5361fdb378d62c69d8257",
        "chainHeight": 11883452
    }"""
    event_data: PolymarketBuySharesEvent
    txHash: str
    chainHeight: int


class PolymarketSellShareTransaction(BaseModel):
    """{
        "event_data": {
            "returnAmount": 22064604,
            "feeAmount": 450298,
            "outcomeTokensSold": 414499991,
            "seller": "0xaaf4acafbb7980ce93631d238eb10a5c4ca67883",
            "outcomeIndex": 0
        },
        "txHash": "0xded32c7363bdd76cef6999b9e6ccde50ddfc2c0a0580f472126bcd9cb2f13d26",
        "chainHeight": 15292615
    }"""
    event_data: PolymarketSellSharesEvent
    txHash: str
    chainHeight: int


class UniswapEpochPairTotalReserves(BaseModel):
    contract: str
    totalReserves: Mapping[str, float]  # block number to corresponding total reserves (in USD?)
    chainHeightRange: EpochBase
    broadcast_id: str
    timestamp: float


class PolymarketLiquiditySnapshotTotal(BaseModel):
    liquidity: int = 0
    outcomeBalances: List[int] = []
    prices: List[float] = []
    chainHeight: int = None


class PolymarketSeedLiquidityRequest(BaseModel):
    contract: str
    chainHeight: int


class PolymarketFundingAddedEvent(BaseModel):
    amountsAdded: List[int]
    sharesMinted: int
    funder: str


class PolymarketFundingAddedTransaction(BaseModel):
    """
        {
        "event_data": {
            "amountsAdded": [
                1000000000,
                553633661
            ],
            "sharesMinted": 744065623,
            "funder": "0xae95a2fd8df6b5e621d583157d47412a6b066579"
        },
        "txHash": "0x98fb3102a3834b500e24560ff6cdf952b0159b83501b0c344fec042e7c4d0db9",
        "chainHeight": 17574335
    }
        """
    event_data: PolymarketFundingAddedEvent
    txHash: str
    chainHeight: int


class PolymarketFundingRemovedEvent(BaseModel):
    amountsRemoved: List[int]
    collateralRemovedFromFeePool: int
    sharesBurnt: int
    funder: str


class PolymarketFundingRemovedTransaction(BaseModel):
    """
    {
        "event_data": {
            "amountsRemoved": [
                9999999999,
                672836672
            ],
            "collateralRemovedFromFeePool": 0,
            "sharesBurnt": 2867674868,
            "funder": "0xe834edad3c89e41243c796d37f262541d65f6da5"
        },
        "txHash": "0x47f7d67b717ab5e33093c487c7cc81f31a2c1ca76fc3cae1adb8f83e0dd2c7a2",
        "chainHeight": 17573629
    }
    """
    event_data: PolymarketFundingRemovedEvent
    txHash: str
    chainHeight: int


class PolymarketLiquidityBase(BaseModel):
    contract: str
    liquidity: float
    outcomeBalances: List[int] = list()
    prices: List[float] = list()
    chainHeight: int
    timestamp: float


class PolymarketLiquiditySnapshot(BaseModel):
    """
        'fundingAdded': list(),
        'fundingRemoved': list(),
        'totalLiquidity': {'liquidity': 0, 'outcomeBalances': list(), 'chainHeight': None},
        'previousLiquidityData': dict()
    """
    fundingAdded: List[PolymarketFundingAddedTransaction] = []
    fundingRemoved: List[PolymarketFundingRemovedTransaction] = []
    # total trade contained within this epoch
    totalLiquidity: PolymarketLiquiditySnapshotTotal = PolymarketLiquiditySnapshotTotal()
    previousLiquidityData: PolymarketLiquidityBase = None


class PolymarketEpochLiquidity(BaseModel):
    contract: str
    chainHeightRange: EpochBase
    broadcast_id: str
    fundingAdded: List[PolymarketFundingAddedTransaction] = list()
    fundingRemoved: List[PolymarketFundingRemovedTransaction] = list()
    timestamp: float


class PolymarketTradeSnapshotTotalTrade(BaseModel):
    tradeVolume: int = 0
    chainHeight: int = None


class PolymarketTradeSnapshot(BaseModel):
    buys: List[PolymarketBuyShareTransaction] = []
    sells: List[PolymarketSellShareTransaction] = []
    # total trade contained within this epoch
    totalTrade: PolymarketTradeSnapshotTotalTrade = PolymarketTradeSnapshotTotalTrade()
    previousCumulativeTrades: PolymarketTradeVolumeBase = None


class ethLogRequestModel(BaseModel):
    fromBlock: int = None
    toBlock: int = None
    contract: str = None
    topics: list = None
    requestId: str = None
    retrialCount: int = 1
