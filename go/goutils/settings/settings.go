package settings

import (
	"encoding/json"
	"math"
	"os"
	"strconv"

	"github.com/go-playground/validator/v10"
	log "github.com/sirupsen/logrus"
	"github.com/swagftw/gi"
)

type RateLimiter struct {
	Burst          int `json:"burst"`
	RequestsPerSec int `json:"req_per_sec"`
}

type PruningServiceSettings struct {
	RunIntervalMins                      int          `json:"run_interval_mins"`
	IPFSRateLimiter                      *RateLimiter `json:"ipfs_rate_limit"`
	Concurrency                          int          `json:"concurrency"`
	CARStoragePath                       string       `json:"car_storage_path"`
	PerformArchival                      bool         `json:"perform_archival"`
	PerformIPFSUnPin                     bool         `json:"perform_ipfs_unpin"`
	PruneRedisZsets                      bool         `json:"prune_redis_zsets"`
	OldestProjectIndex                   string       `json:"oldest_project_index"`
	BackUpRedisZSets                     bool         `json:"backup_redis_zsets_to_file"`
	IpfsTimeout                          int          `json:"ipfs_timeout_secs"`
	SummaryProjectsPruneHeightBehindHead int          `json:"summary_projects_prune_height_behind_head"`
	PruningHeightBehindOldestIndex       int          `json:"pruning_height_behind_oldest_index"`
	SegmentSize                          int          `json:"segment_size"`
	Web3Storage                          struct {
		TimeoutSecs       int          `json:"timeout_secs"`
		RateLimit         *RateLimiter `json:"rate_limit"`
		UploadChunkSizeMB int          `json:"upload_chunk_size_mb"`
	} `json:"web3_storage"`
}

// DagVerifierSettings - names should not contain _
type DagVerifierSettings struct {
	Host                         string       `json:"host"`
	Port                         int          `json:"port"`
	SlackNotifyURL               string       `json:"slack_notify_URL"`
	RunIntervalSecs              int          `json:"run_interval_secs"`
	SuppressNotificationTimeSecs int64        `json:"suppress_notification_for_secs"`
	SummaryProjectsToTrack       []string     `json:"additional_projects_to_track_prefixes"`
	IPFSRateLimiter              *RateLimiter `json:"ipfs_rate_limit,omitempty"`
	Concurrency                  int          `json:"concurrency"`
	RedisPoolSize                int          `json:"redis_pool_size"`
	PruningVerification          bool         `json:"pruning_verification"`
}

type TokenAggregatorSettings struct {
	Port            int    `json:"port"`
	RunIntervalSecs int    `json:"run_interval_secs"`
	APHost          string `json:"ap_host"`
}

type SettingsObj struct {
	APBackend struct {
		Host          string `json:"host"`
		Port          int    `json:"port"`
		KeepAliveSecs int    `json:"keepalive_secs"`
	} `json:"ap_backend"`
	DAGFinalizer struct {
		Host string `json:"host"`
		Port int    `json:"port"`
	} `json:"dag_finalizer"`
	IpfsConfig struct {
		URL             string       `json:"url"`
		ReaderURL       string       `json:"reader_url"`
		IPFSRateLimiter *RateLimiter `json:"write_rate_limit,omitempty"`
		Timeout         int          `json:"timeout"`
	} `json:"ipfs"`
	Rlimit struct {
		FileDescriptors int `json:"file_descriptors"`
	} `json:"rlimit"`
	Rabbitmq struct {
		User     string `json:"user"`
		Password string `json:"password"`
		Host     string `json:"host"`
		Port     int    `json:"port"`
		Setup    struct {
			Core struct {
				Exchange string `json:"exchange"`
			} `json:"core"`
			CommitPayload struct {
				Exchange string `json:"exchange"`
			} `json:"commit_payload"`
		} `json:"setup"`
	} `json:"rabbitmq"`
	ContractCallBackend struct {
		URL                     string       `json:"url"`
		RateLimiter             *RateLimiter `json:"rate_limit,omitempty"`
		SkipSummaryProjectProof bool         `json:"skip_summary_projects_anchor_proof"`
	} `json:"txn_config"`
	RetryCount            *int `json:"retry_count"`
	RetryIntervalSecs     int  `json:"retry_interval_secs"`
	HttpClientTimeoutSecs int  `json:"http_client_timeout_secs"`
	Redis                 struct {
		Host     string `json:"host"`
		Port     int    `json:"port"`
		Db       int    `json:"db"`
		Password string `json:"password"`
	} `json:"redis"`
	RedisReader struct {
		Host     string `json:"host"`
		Port     int    `json:"port"`
		Db       int    `json:"db"`
		Password string `json:"password"`
	} `json:"redis_reader"`
	PayloadCommit struct {
		Concurrency             int          `json:"concurrency"`
		DAGFinalizerRateLimiter *RateLimiter `json:"dag_finalizer_rate_limit,omitempty"`
	} `json:"payload_commit"`
	Web3Storage struct {
		URL             string       `json:"url"`
		APIToken        string       `json:"api_token"`
		TimeoutSecs     int          `json:"timeout_secs"`
		MaxIdleConns    int          `json:"max_idle_conns"`
		IdleConnTimeout int          `json:"idle_conn_timeout"`
		RateLimiter     *RateLimiter `json:"rate_limit,omitempty"`
		UploadURLSuffix string       `json:"upload_url_suffix"`
	} `json:"web3_storage"`
	Relayer struct {
		Host     *string `json:"host" validate:"required"`
		Endpoint *string `json:"endpoint" validate:"required"`
	} `json:"relayer" validate:"required,dive"`
	UseConsensus     bool             `json:"use_consensus"`
	ConsensusConfig  ConsensusConfig_ `json:"consensus_config"`
	InstanceId       string           `json:"instance_id"`
	PayloadCachePath string           `json:"local_cache_path"`
	PoolerNamespace  string           `json:"pooler_namespace"`
	Signer           *Signer          `json:"signer"`
	EpochSize        int              `json:"epoch_size"`
}

type Signer struct {
	Domain struct {
		Name              string `json:"name"`
		Version           string `json:"version"`
		ChainId           string `json:"chainId"`
		VerifyingContract string `json:"verifyingContract"`
	} `json:"domain"`
	AccountAddress string `json:"accountAddress"`
	PrivateKey     string `json:"privateKey"`
	DeadlineBuffer int    `json:"deadlineBuffer"`
	RpcUrl         string `json:"rpcUrl"`
}

type ConsensusConfig_ struct {
	ServiceURL          string       `json:"service_url"`
	RateLimiter         *RateLimiter `json:"rate_limit"`
	TimeoutSecs         int          `json:"timeout_secs"`
	MaxIdleConns        int          `json:"max_idle_conns"`
	IdleConnTimeout     int          `json:"idle_conn_timeout"`
	FinalizationWaiTime int64        `json:"finalization_wait_time_secs"`
	PollingIntervalSecs int          `json:"polling_interval_secs"`
}

func ParseSettings() *SettingsObj {
	v := validator.New()

	// Go variables & constants should be camel cased.
	settingsFilePath := os.Getenv("CONFIG_PATH") + "/settings.json"
	settingsObj := new(SettingsObj)

	log.Info("Reading Settings:", settingsFilePath)

	data, err := os.ReadFile(settingsFilePath)
	if err != nil {
		log.Error("Cannot read the file:", err)
		panic(err)
	}

	log.Debug("Settings json data is", string(data))

	err = json.Unmarshal(data, settingsObj)
	if err != nil {
		log.Error("Cannot unmarshal the settings json ", err)
		panic(err)
	}

	err = v.Struct(settingsObj)
	if err != nil {
		log.WithError(err).Fatal("Invalid settings object")
	}

	SetDefaults(settingsObj)
	log.Infof("Final Settings Object being used %+v", settingsObj)

	err = gi.Inject(settingsObj)
	if err != nil {
		log.Fatal("Cannot inject the settings object", err)
	}

	return settingsObj
}

func SetDefaults(settingsObj *SettingsObj) {
	// Set defaults for settings that are not configured.
	if settingsObj.RetryCount == nil {
		settingsObj.RetryCount = new(int)
		*settingsObj.RetryCount = 10
	} else if *settingsObj.RetryCount == 0 { // This means retry unlimited number of times.
		*settingsObj.RetryCount = math.MaxInt
	}
	if settingsObj.RetryIntervalSecs == 0 {
		settingsObj.RetryIntervalSecs = 5
	}
	if settingsObj.HttpClientTimeoutSecs == 0 {
		settingsObj.HttpClientTimeoutSecs = 10
	}
	if settingsObj.PayloadCommit.Concurrency == 0 {
		settingsObj.PayloadCommit.Concurrency = 20
	}
	if settingsObj.Web3Storage.UploadURLSuffix == "" {
		settingsObj.Web3Storage.UploadURLSuffix = "/upload"
	}

	// for local testing
	if val, err := strconv.ParseBool(os.Getenv("LOCAL_TESTING")); err == nil && val {
		settingsObj.Redis.Host = "localhost"
		settingsObj.RedisReader.Host = "localhost"
		settingsObj.Rabbitmq.Host = "localhost"
		settingsObj.IpfsConfig.ReaderURL = "/dns/localhost/tcp/5001"
		settingsObj.IpfsConfig.URL = "/dns/localhost/tcp/5001"
	}

	privKey := os.Getenv("PRIVATE_KEY")
	if privKey != "" {
		settingsObj.Signer.PrivateKey = privKey
	}
}
