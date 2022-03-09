package main

type AuditProtocolErrorResp struct {
	Error string `json:error`
}

type AuditProtocolBlockHeightResp struct {
	Height int `json:"height"`
}

type TokenData struct {
	Name            string  `json:name`
	Symbol          string  `json:symbol`
	Price           float64 `json:price`
	Liquidity       float64 `json:liquidity`
	TradeVolume_24h float64 `json:tradeVolume_24h`
}

// Struct auto-generated from https://mholt.github.io/json-to-go/ by pasting sample json
//Had to modify places where maps are required.

type TokenPairReserves struct {
	DagCid string `json:"dagCid"`
	Data   struct {
		Cid     string `json:"cid"`
		Type    string `json:"type"`
		Payload struct {
			Contract         string             `json:"contract"`
			Token0Reserves   map[string]float64 `json:"token0Reserves"`
			Token1Reserves   map[string]float64 `json:"token1Reserves"`
			ChainHeightRange struct {
				Begin int64 `json:"begin"`
				End   int64 `json:"end"`
			} `json:"chainHeightRange"`
			BroadcastID string  `json:"broadcast_id"`
			Timestamp   float64 `json:"timestamp"`
		} `json:"payload"`
	} `json:"data"`
	Height         int64  `json:"height"`
	Timestamp      int64  `json:"timestamp"`
	TxHash         string `json:"txHash"`
	PrevDagCid     string `json:"prevDagCid"`
	PayloadChanged bool   `json:"payloadChanged"`
	Diff           struct {
		Token0Reserves struct {
			Old map[string]float64 `json:"old"`
			New map[string]float64 `json:"new"`
		} `json:"token0Reserves"`
		Token1Reserves struct {
			Old map[string]float64 `json:"old"`
			New map[string]float64 `json:"new"`
		} `json:"token1Reserves"`
	} `json:"diff"`
}

// Struct auto-generated from https://mholt.github.io/json-to-go/ by pasting sample json
//TODO: Refer to uniswap contract and change all fields which are uint256 to bigInt.
type TokenPairTradeVolumeData struct {
	DagCid string `json:"dagCid"`
	Data   struct {
		Cid     string `json:"cid"`
		Type    string `json:"type"`
		Payload struct {
			Contract          string  `json:"contract"`
			TotalTrade        float64 `json:"totalTrade"`
			Token0TradeVolume float64 `json:"token0TradeVolume"`
			Token1TradeVolume float64 `json:"token1TradeVolume"`
			Events            []struct {
				Sender string `json:"sender"`
				To     string `json:"to"`
				/* Commenting these for now as there are samples which go beyond int64.
				Need to handle it via some bigInt if required.
				Amount0In  int64 `json:"amount0In"`
				Amount1In  int64   `json:"amount1In"`
				Amount0Out int64   `json:"amount0Out"`
				Amount1Out int64   `json:"amount1Out"`*/
			} `json:"events"`
			ChainHeightRange struct {
				Begin int64 `json:"begin"`
				End   int64 `json:"end"`
			} `json:"chainHeightRange"`
			BroadcastID string  `json:"broadcast_id"`
			Timestamp   float64 `json:"timestamp"`
		} `json:"payload"`
	} `json:"data"`
	Height         int64  `json:"height"`
	Timestamp      int64  `json:"timestamp"`
	TxHash         string `json:"txHash"`
	PrevDagCid     string `json:"prevDagCid"`
	PayloadChanged bool   `json:"payloadChanged"`
	Diff           struct {
		TotalTrade struct {
			Old float64 `json:"old"`
			New float64 `json:"new"`
		} `json:"totalTrade"`
		Token0TradeVolume struct {
			Old float64 `json:"old"`
			New float64 `json:"new"`
		} `json:"token0TradeVolume"`
		Token1TradeVolume struct {
			Old float64 `json:"old"`
			New float64 `json:"new"`
		} `json:"token1TradeVolume"`
	} `json:"diff"`
}

type ProjectSettings struct {
	Development struct {
		ContractAddresses struct {
			IuniswapV2Factory string `json:"iuniswap_v2_factory"`
			IuniswapV2Router  string `json:"iuniswap_v2_router"`
			IuniswapV2Pair    string `json:"iuniswap_v2_pair"`
			Usdt              string `json:"USDT"`
			Dai               string `json:"DAI"`
			Usdc              string `json:"USDC"`
			Weth              string `json:"WETH"`
			WETHUSDT          string `json:"WETH-USDT"`
		} `json:"contract_addresses"`
		IpfsURL          string `json:"ipfs_url"`
		UniswapFunctions struct {
			ThreadingSemaphore int `json:"threading_semaphore"`
			SemaphoreWorkers   int `json:"semaphore_workers"`
			RetrialAttempts    int `json:"retrial_attempts"`
		} `json:"uniswap_functions"`
		Namespace string `json:"namespace"`
		RPC       struct {
			Matic      []string `json:"matic"`
			EthMainnet string   `json:"eth_mainnet"`
			LogsQuery  struct {
				Chunk   int `json:"chunk"`
				Retry   int `json:"retry"`
				Timeout int `json:"timeout"`
			} `json:"logs_query"`
			Retry     int    `json:"retry"`
			RateLimit string `json:"rate_limit"`
			APIKey    string `json:"API_KEY"`
		} `json:"rpc"`
		EthLogWorker struct {
			Semaphore         int    `json:"semaphore"`
			Subtopic          string `json:"subtopic"`
			ReceiverQueueName string `json:"receiver_queue_name"`
			SenderQueueName   string `json:"sender_queue_name"`
			ReceiverQueue     string `json:"receiver_queue"`
			SenderQueue       string `json:"sender_queue"`
			Host              string `json:"host"`
			Port              int    `json:"port"`
		} `json:"eth_log_worker"`
		Epoch struct {
			Height     int `json:"height"`
			HeadOffset int `json:"head_offset"`
			BlockTime  int `json:"block_time"`
		} `json:"epoch"`
		Rabbitmq struct {
			User     string `json:"user"`
			Password string `json:"password"`
			Host     string `json:"host"`
			Port     int    `json:"port"`
			Setup    struct {
				Core struct {
					Exchange string `json:"exchange"`
				} `json:"core"`
				Callbacks struct {
					Exchange string   `json:"exchange"`
					Path     string   `json:"path"`
					Config   string   `json:"config"`
					Services []string `json:"services"`
				} `json:"callbacks"`
			} `json:"setup"`
		} `json:"rabbitmq"`
		Rlimit struct {
			FileDescriptors int `json:"file_descriptors"`
		} `json:"rlimit"`
		Timeouts struct {
			Basic          int `json:"basic"`
			Archival       int `json:"archival"`
			ConnectionInit int `json:"connection_init"`
		} `json:"timeouts"`
		Zookeeper struct {
			User     string `json:"user"`
			Password string `json:"password"`
			Host     string `json:"host"`
			Port     int    `json:"port"`
		} `json:"zookeeper"`
		Host                string `json:"host"`
		Port                int    `json:"port"`
		AuditProtocolEngine struct {
			URL   string `json:"url"`
			Retry int    `json:"retry"`
		} `json:"audit_protocol_engine"`
		AuditProtocolEngine2 struct {
			URL   string `json:"url"`
			Retry int    `json:"retry"`
		} `json:"audit_protocol_engine_2"`
		SnapshotMaxWorkers       int `json:"snapshot_max_workers"`
		SnapshotMaticvigilLimits struct {
			MaxAcquisitionTries int `json:"max_acquisition_tries"`
			AcquisitionSleep    int `json:"acquisition_sleep"`
			MaxWorkers          int `json:"max_workers"`
		} `json:"snapshot_maticvigil_limits"`
		ActorSemaphoreLimits struct {
			RPC struct {
				MaxAcquisitionTries int `json:"max_acquisition_tries"`
				AcquisitionSleep    int `json:"acquisition_sleep"`
			} `json:"rpc"`
		} `json:"actor_semaphore_limits"`
		PayloadAttrsFilter []string `json:"payload_attrs_filter"`
		Redis              struct {
			Host        string      `json:"host"`
			Port        int         `json:"port"`
			Db          int         `json:"db"`
			Password    interface{} `json:"password"`
			Ssl         bool        `json:"ssl"`
			ClusterMode bool        `json:"cluster_mode"`
		} `json:"redis"`
		RedisReader struct {
			Host     string      `json:"host"`
			Port     int         `json:"port"`
			Db       int         `json:"db"`
			Password interface{} `json:"password"`
		} `json:"redis_reader"`
		TradeVolSnapshotInterval int    `json:"trade_vol_snapshot_interval"`
		VerifyAbiEndpoint        string `json:"verify_abi_endpoint"`
		CheckContractEndpoint    string `json:"check_contract_endpoint"`
		VerifyContractEndpoint   string `json:"verify_contract_endpoint"`
		ActivateHookEndpoint     string `json:"activate_hook_endpoint"`
		DeactivateHookEndpoint   string `json:"deactivate_hook_endpoint"`
		UpdateHookEventsEndpoint string `json:"update_hook_events_endpoint"`
		AddHookEndpoint          string `json:"add_hook_endpoint"`
		LoginEndpoint            string `json:"login_endpoint"`
		WebhookListener          struct {
			Host                           string `json:"host"`
			Port                           int    `json:"port"`
			Root                           string `json:"root"`
			MarketEventListenerPath        string `json:"market_event_listener_path"`
			CommitConfirmationCallbackPath string `json:"commit_confirmation_callback_path"`
		} `json:"webhook_listener"`
		EventConfirmationBlockHeight        int `json:"event_confirmation_block_height"`
		EventCacheCollectionChainHeadOffset int `json:"event_cache_collection_chain_head_offset"`
		MaticVigilKeys                      struct {
			PrivateKey string `json:"private_key"`
			ReadKey    string `json:"read_key"`
			APIKey     string `json:"api_key"`
		} `json:"matic_vigil_keys"`
		SubgraphURL              string `json:"subgraph_url"`
		OffchainSnapshotInterval int    `json:"offchain_snapshot_interval"`
		OnchainSnapshotInterval  int    `json:"onchain_snapshot_interval"`
		MaticRPCURL              string `json:"matic_rpc_url"`
		EthLogsTimeout           int    `json:"eth_logs_timeout"`
		ForceHookAdd             bool   `json:"force_hook_add"`
		ForceAddNewHookID        bool   `json:"force_add_new_hook_id"`
		ClientSessionTimeout     struct {
			SockRead    int `json:"sock_read"`
			Connect     int `json:"connect"`
			SockConnect int `json:"sock_connect"`
			Total       int `json:"total"`
		} `json:"client_session_timeout"`
		SeedingRetryLimits struct {
			Liquidity int `json:"liquidity"`
			TradeVol  int `json:"trade_vol"`
		} `json:"seeding_retry_limits"`
		ForceSeedTradeVolume   bool `json:"force_seed_trade_volume"`
		ForceSeedLiquidity     bool `json:"force_seed_liquidity"`
		ForceSeedOutcomePrices bool `json:"force_seed_outcome_prices"`
		PendingCommitTimeout   int  `json:"pending_commit_timeout"`
		UpdatePairsInterval    int  `json:"UPDATE_PAIRS_INTERVAL"`
	} `json:"development"`
}
