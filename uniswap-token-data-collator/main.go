package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io/ioutil"
	"net/http"
	"os"
	"strconv"
	"time"

	log "github.com/sirupsen/logrus"
	"github.com/sirupsen/logrus/hooks/writer"

	"github.com/ethereum/go-ethereum/common"

	"github.com/go-redis/redis"
)

var settingsObj ProjectSettings
var redisClient *redis.Client
var pairContracts []string
var tokenList map[string]*TokenData
var apHttpClient http.Client
var lastSnapshotBlockHeight int64

var tokenPairTokenMapping map[string]TokenDataRefs

type TokenDataRefs struct {
	token0Ref *TokenData
	token1Ref *TokenData
}

const settingsFile string = "../settings.json"
const pairContractListFile string = "../static/cached_pair_addresses.json"
const V2_PAIRSUMMARY_PROJECTID string = "uniswap_V2PairsSummarySnapshot_%s"
const V2_TOKENSUMMARY_PROJECTID string = "uniswap_V2TokensSummarySnapshot_%s"
const MAX_RETRIES_BEFORE_EXIT int = 10
const MAX_RETRIES_FOR_SNAPSHOT_CONFIRM = 5

//TODO: Move the below to config file.
const periodicRetrievalInterval time.Duration = 60 * time.Second

//const maxBlockCountToFetch int64 = 500 //Max number of blocks to fetch in 1 shot from Audit Protocol.

func main() {
	var pairContractAddressesFile string
	log.SetOutput(ioutil.Discard) // Send all logs to nowhere by default
	log.SetReportCaller(true)
	log.AddHook(&writer.Hook{ // Send logs with level higher than warning to stderr
		Writer: os.Stderr,
		LogLevels: []log.Level{
			log.PanicLevel,
			log.FatalLevel,
			log.ErrorLevel,
			log.WarnLevel,
		},
	})
	log.AddHook(&writer.Hook{ // Send info and debug logs to stdout
		Writer: os.Stdout,
		LogLevels: []log.Level{
			log.TraceLevel,
			log.InfoLevel,
			log.DebugLevel,
		},
	})
	if len(os.Args) < 2 {
		fmt.Println("Pass loglevel as an argument if you don't want default(INFO) to be set.")
		fmt.Println("Values to be passed for logLevel: ERROR(2),INFO(4),DEBUG(5)")
		log.SetLevel(log.InfoLevel)
	} else {
		logLevel, err := strconv.ParseUint(os.Args[1], 10, 32)
		if err != nil || logLevel > 6 {
			log.SetLevel(log.InfoLevel)
		} else {
			//TODO: Need to come up with approach to dynamically update logLevel.
			log.SetLevel(log.Level(logLevel))
		}
	}
	log.SetFormatter(&log.TextFormatter{FullTimestamp: true})
	if len(os.Args) == 3 {
		pairContractAddressesFile = os.Args[2]
	}

	ReadSettings()
	SetupRedisClient()
	InitAuditProtocolClient()
	tokenList = make(map[string]*TokenData)
	tokenPairTokenMapping = make(map[string]TokenDataRefs)
	Run(pairContractAddressesFile)

}

func Run(pairContractAddress string) {
	PopulatePairContractList(pairContractAddress)
	var v2SummaryBlockHeight int64
	for {
		log.Info("Waiting for first V2 Summary snapshot to be formed...")
		v2SummaryBlockHeight = FetchV2SummaryLatestBlockHeight()
		if v2SummaryBlockHeight != 0 {
			log.Infof("v2Summary snapshot has been created at height %d", v2SummaryBlockHeight)
			break
		}
		time.Sleep(periodicRetrievalInterval)
	}

	FetchTokensMetaData()

	for {
		PrepareAndSubmitV2TokenSummarySnapshot()

		log.Info("Sleeping for " + periodicRetrievalInterval.String() + " secs")
		time.Sleep(periodicRetrievalInterval)
	}
}

func FetchTokensMetaData() {
	for i := range pairContracts {
		pairContractAddress := pairContracts[i]
		pairContractAddr := common.HexToAddress(pairContractAddress).Hex()
		FetchAndFillTokenMetaData(pairContractAddr)
	}
}

func FetchAndFillTokenMetaData(pairContractAddr string) {
	redisKey := fmt.Sprintf(REDIS_KEY_TOKEN_PAIR_CONTRACT_TOKENS_DATA, settingsObj.Development.Namespace, pairContractAddr)
	log.Debug("Fetching PairContractTokensData from redis with key:", redisKey)
	var tokenPairMeta map[string]string
	var err error
	for retryCount := 0; ; {
		tokenPairMeta, err = redisClient.HGetAll(redisKey).Result()
		if err != nil {
			retryCount++
			if retryCount > MAX_RETRIES_BEFORE_EXIT {
				log.Fatalf("Unable to fetch PairContractTokensData for %s key even after max retries %d . Hence exiting...",
					MAX_RETRIES_BEFORE_EXIT, redisKey)
				os.Exit(1)
			}
			log.Errorf("Failed to get tokenPair MetaData from redis for PairContract %s due to error %s, retrying %d",
				pairContractAddr, err.Error(), retryCount)
			time.Sleep(10 * time.Second)
			continue
		}
		log.Debug("Fetched PairContractTokensData from redis:", tokenPairMeta)
		break
	}

	//Use tokenContractAddress to store tokenData as tokenSymbol is not gauranteed to be unique.
	var tokenContractAddresses map[string]string
	redisKey = fmt.Sprintf(REDIS_KEY_PAIR_TOKEN_ADDRESSES, settingsObj.Development.Namespace, pairContractAddr)
	for retryCount := 0; ; {
		tokenContractAddresses, err = redisClient.HGetAll(redisKey).Result()
		if err != nil {
			retryCount++
			if retryCount > MAX_RETRIES_BEFORE_EXIT {
				log.Fatalf("Unable to fetch PairContractTokensAddresses for %s key even after max retries %d. Hence exiting...",
					MAX_RETRIES_BEFORE_EXIT, redisKey)
				os.Exit(1)
			}
			log.Errorf("Failed to get PairContractTokensAddresses from redis for PairContract due to error %s, retrying %d",
				pairContractAddr, err.Error(), retryCount)
			time.Sleep(10 * time.Second)
			continue
		}
		log.Debugf("Fetched PairContractTokensAddresses from redis %+v", tokenContractAddresses)
		break
	}
	token0Addr := tokenContractAddresses["token0Addr"]
	token1Addr := tokenContractAddresses["token1Addr"]
	var tokenRefs TokenDataRefs
	//FIX: TOKEN Symbol and name not getting stored in tokenData.
	if _, ok := tokenList[token0Addr]; !ok {
		var tokenData TokenData
		tokenData.Symbol = tokenPairMeta["token0_symbol"]
		tokenData.Name = tokenPairMeta["token0_name"]
		tokenData.ContractAddress = token0Addr
		tokenList[token0Addr] = &tokenData
		tokenRefs.token0Ref = &tokenData
		log.Debugf("Token0 Data : %+v", tokenData)
	}
	tokenRefs.token0Ref = tokenList[token0Addr]
	if _, ok := tokenList[token1Addr]; !ok {
		var tokenData TokenData
		tokenData.Symbol = tokenPairMeta["token1_symbol"]
		tokenData.Name = tokenPairMeta["token1_name"]
		tokenData.ContractAddress = token1Addr
		tokenList[token1Addr] = &tokenData
		tokenRefs.token1Ref = &tokenData
		log.Debugf("Token1 Data: %+v", tokenData)
	}
	tokenRefs.token1Ref = tokenList[token1Addr]
	tokenPairTokenMapping[pairContractAddr] = tokenRefs
}

func PrepareAndSubmitV2TokenSummarySnapshot() {

	curBlockHeight := FetchV2SummaryLatestBlockHeight()
	if curBlockHeight > lastSnapshotBlockHeight {
		var sourceBlockHeight int64
		tokensPairData := FetchV2PairSummarySnapshot(curBlockHeight)
		log.Debugf("Collating tokenData at blockHeight %d", curBlockHeight)
		for _, tokenPairProcessedData := range tokensPairData {
			//TODO: Need to remove 0x from contractAddress saved as string.
			token0Data := tokenPairTokenMapping[common.HexToAddress(tokenPairProcessedData.ContractAddress).Hex()].token0Ref
			token1Data := tokenPairTokenMapping[common.HexToAddress(tokenPairProcessedData.ContractAddress).Hex()].token1Ref

			token0Data.Liquidity += tokenPairProcessedData.Token0Liquidity
			token0Data.LiquidityUSD += tokenPairProcessedData.Token0LiquidityUSD

			token1Data.Liquidity += tokenPairProcessedData.Token1Liquidity
			token1Data.LiquidityUSD += tokenPairProcessedData.Token1LiquidityUSD

			token0Data.TradeVolume_24h += tokenPairProcessedData.Token0TradeVolume_24h
			token0Data.TradeVolumeUSD_24h += tokenPairProcessedData.Token0TradeVolumeUSD_24h

			token1Data.TradeVolume_24h += tokenPairProcessedData.Token1TradeVolume_24h
			token1Data.TradeVolumeUSD_24h += tokenPairProcessedData.Token1TradeVolumeUSD_24h

			token0Data.TradeVolume_7d += tokenPairProcessedData.Token0TradeVolume_7d
			token0Data.TradeVolumeUSD_7d += tokenPairProcessedData.Token0TradeVolumeUSD_7d

			token1Data.TradeVolume_7d += tokenPairProcessedData.Token1TradeVolume_7d
			token1Data.TradeVolumeUSD_7d += tokenPairProcessedData.Token1TradeVolumeUSD_7d

			token0Data.Block_height = tokenPairProcessedData.Block_height
			token1Data.Block_height = tokenPairProcessedData.Block_height

			token0Data.Block_timestamp = tokenPairProcessedData.Block_timestamp
			token1Data.Block_timestamp = tokenPairProcessedData.Block_timestamp
			sourceBlockHeight = int64(tokenPairProcessedData.Block_height)
		}

		tm, err := strconv.ParseInt(fmt.Sprint(tokensPairData[0].Block_timestamp), 10, 64)
		if err != nil {
			log.Errorf("Failed to parse current timestamp int %s due to error %s", tokensPairData[0].Block_timestamp, err.Error())
			return
		}
		currentTimestamp := time.Unix(tm, 0)
		toTime := float64(currentTimestamp.Unix())

		time24h := currentTimestamp.AddDate(0, 0, -1)
		fromTime := float64(time24h.Unix())
		log.Debug("TimeStamp for 1 day before is:", fromTime)
		//TODO: Fetch lastTokensummaryBlockHeight for the project
		lastTokensummaryBlockHeight := FetchTokenSummaryLatestBlockHeight()
		//Update tokenPrice
		for key, tokenData := range tokenList {
			tokenData.Price = FetchTokenPriceAtBlockHeight(tokenData.ContractAddress, int64(tokenData.Block_height))
			if tokenData.Price != 0 {
				//Update TokenPrice in History Zset
				UpdateTokenPriceHistoryRedis(toTime, fromTime, tokenData)
				CalculateAndFillPriceChange(fromTime, tokenData)
				//tokenList[key] = tokenData
			} else {
				//TODO: Should we create a snapshot if we don't have any tokenPrice at specified height?
				log.Errorf("Price couldn't be retrieved for token %s with name %s at blockHeight %d hence removing token from the list.",
					key, tokenData.Name, tokenData.Block_height)
				//delete(tokenList, key)
			}
		}
		err = CommitV2TokenSummaryPayload()
		if err != nil {
			log.Errorf("Failed to commit payload at blockHeight %d due to error %s", curBlockHeight, err.Error())
			ResetTokenData()
			return
		}
		tentativeBlockHeight := lastTokensummaryBlockHeight + 1
		payloadCID, txHash, err := WaitAndFetchBlockHeightStatus(tentativeBlockHeight, MAX_RETRIES_FOR_SNAPSHOT_CONFIRM)
		if err != nil {
			log.Errorf("Failed to Fetch payloadCID at blockHeight %d due to error %s", tentativeBlockHeight, err.Error())
			ResetTokenData()
			return
		}
		StoreTokenSummaryCIDInSnapshotsZSet(sourceBlockHeight, payloadCID, txHash)
		StoreV2TokensSummaryPayload(sourceBlockHeight)
		ResetTokenData()
		lastSnapshotBlockHeight = curBlockHeight

		//Prune TokenPrice ZSet as price already fetched for all tokens
		for _, tokenData := range tokenList {
			PruneTokenPriceZSet(tokenData.ContractAddress, int64(tokenData.Block_height))
		}
	} else {
		log.Debugf("PairSummary blockHeight has not moved yet and is still at %d, lastSnapshotBlockHeight is %d. Hence not processing anything.",
			curBlockHeight, lastSnapshotBlockHeight)
	}
}

func FetchTokenSummaryLatestBlockHeight() int64 {
	v2PairsProjectId := fmt.Sprintf(V2_TOKENSUMMARY_PROJECTID, settingsObj.Development.Namespace)
	last_block_height_url := settingsObj.Development.AuditProtocolEngine.URL + "/" + v2PairsProjectId + "/payloads/height"
	log.Debug("Fetching Blockheight URL:", last_block_height_url)
	var heightResp AuditProtocolBlockHeightResp

	for retryCount := 0; retryCount < 3; retryCount++ {
		resp, err := apHttpClient.Get(last_block_height_url)
		if err != nil {
			log.Error("Error: Could not fetch block height for pairContract:", v2PairsProjectId, " Error:", err)
			time.Sleep(5 * time.Second)
			continue
		}
		defer resp.Body.Close()
		body, err := ioutil.ReadAll(resp.Body)
		if err != nil {
			log.Error("Unable to read HTTP resp.", err)
			return 0
		}
		log.Trace("Rsp Body", string(body))

		if err = json.Unmarshal(body, &heightResp); err != nil { // Parse []byte to the go struct pointer
			log.Errorf("Can not unmarshal JSON resp for due to error %+v", err)
			continue
		}
		break
	}
	log.Debugf("Last Block Height for projectID %s is : %d", v2PairsProjectId, heightResp.Height)
	return heightResp.Height
}

func ResetTokenData() {
	for _, tokenData := range tokenList {
		tokenData.Liquidity = 0
		tokenData.LiquidityUSD = 0
		tokenData.TradeVolume_24h = 0
		tokenData.TradeVolumeUSD_24h = 0
		tokenData.TradeVolume_7d = 0
		tokenData.TradeVolumeUSD_7d = 0
	}
}

func CalculateAndFillPriceChange(fromTime float64, tokenData *TokenData) {
	curTimeEpoch := float64(time.Now().Unix())
	key := fmt.Sprintf(REDIS_KEY_TOKEN_PRICE_HISTORY, settingsObj.Development.Namespace, tokenData.ContractAddress)

	zRangeByScore := redisClient.ZRangeByScore(key, redis.ZRangeBy{
		Min: fmt.Sprintf("%f", fromTime),
		Max: fmt.Sprintf("%f", curTimeEpoch),
	})
	if zRangeByScore.Err() != nil {
		log.Error("Could not fetch entries error: ", zRangeByScore.Err().Error(), "fromTime:", fromTime)
		return
	}
	//Fetch the oldest Value closest to 24h
	var tokenPriceHistoryEntry TokenPriceHistoryEntry
	err := json.Unmarshal([]byte(zRangeByScore.Val()[0]), &tokenPriceHistoryEntry)
	if err != nil {
		log.Error("Unable to decode value fetched from Zset...something wrong!!")
		return
	}
	//TODO: Need to add validation if value is newer than x hours, should we still show as priceChange?
	oldPrice := tokenPriceHistoryEntry.Price
	tokenData.PriceChangePercent_24h = (tokenData.Price - oldPrice) * 100 / tokenData.Price
}

func UpdateTokenPriceHistoryRedis(toTime float64, fromTime float64, tokenData *TokenData) {
	key := fmt.Sprintf(REDIS_KEY_TOKEN_PRICE_HISTORY, settingsObj.Development.Namespace, tokenData.ContractAddress)
	var priceHistoryEntry TokenPriceHistoryEntry = TokenPriceHistoryEntry{toTime, tokenData.Price, tokenData.Block_height}
	val, err := json.Marshal(priceHistoryEntry)
	if err != nil {
		log.Error("Couldn't marshal json..something is really wrong with data.curTime:", toTime, " TokenData:", tokenData)
		return
	}
	err = redisClient.ZAdd(key, redis.Z{
		Score:  float64(toTime),
		Member: string(val),
	}).Err()
	if err != nil {
		log.Error("Failed to add to redis ZSet, err:", err, " key :", key, ", Value:", val)
	}
	log.Debug("Updated TokenPriceHistory at Zset:", key, " with score:", toTime, ",val:", priceHistoryEntry)

	PrunePriceHistoryInRedis(key, fromTime)
}

func PrunePriceHistoryInRedis(key string, fromTime float64) {
	//Remove any entries older than 1 hour from fromTime.
	res := redisClient.ZRemRangeByScore(key, fmt.Sprintf("%f", 0.0),
		fmt.Sprintf("%f", fromTime-60*60))
	if res.Err() != nil {
		log.Error("Pruning entries at key:", key, "failed with error:", res.Err().Error())
	}
	log.Debug("Pruning: Removed ", res.Val(), " entries in redis Zset at key:", key)
}

func PruneTokenPriceZSet(tokenContractAddr string, blockHeight int64) {
	redisKey := fmt.Sprintf(REDIS_KEY_TOKEN_BLOCK_HEIGHT_PRICE, settingsObj.Development.Namespace, tokenContractAddr)
	res := redisClient.ZRemRangeByScore(
		redisKey,
		"-inf",
		fmt.Sprintf("%d", blockHeight))
	if res.Err() != nil {
		log.Error("Pruning entries at key:", redisKey, "failed with error:", res.Err().Error())
	}
	log.Debug("Pruning: Removed ", res.Val(), " entries in redis Zset at key:", redisKey)
}

func FetchTokenPriceAtBlockHeight(tokenContractAddr string, blockHeight int64) float64 {

	redisKey := fmt.Sprintf(REDIS_KEY_TOKEN_BLOCK_HEIGHT_PRICE, settingsObj.Development.Namespace, tokenContractAddr)
	type tokenPriceAtBlockHeight struct {
		BlockHeight int     `json:"blockHeight"`
		Price       float64 `json:"price"`
	}
	var tokenPriceAtHeight tokenPriceAtBlockHeight
	tokenPriceAtHeight.Price = 0
	for retryCount := 0; retryCount < 3; retryCount++ {
		zRangeByScore := redisClient.ZRangeByScore(redisKey, redis.ZRangeBy{
			Min: fmt.Sprintf("%d", blockHeight),
			Max: fmt.Sprintf("%d", blockHeight),
		})
		if zRangeByScore.Err() != nil {
			log.Errorf("Failed to fetch tokenPrice for contract %s at blockHeight %d due to error %s, retrying %d",
				tokenContractAddr, zRangeByScore.Err().Error(), blockHeight, retryCount)
			time.Sleep(5 * time.Second)
			continue
		}
		if len(zRangeByScore.Val()) == 0 {
			log.Error("Could not fetch tokenPrice for contract ", tokenContractAddr, " at BlockHeight:", blockHeight, " and hence will be set to 0")
			return tokenPriceAtHeight.Price
		}

		err := json.Unmarshal([]byte(zRangeByScore.Val()[0]), &tokenPriceAtHeight)
		if err != nil {
			log.Fatalf("Unable to parse tokenPrice retrieved from redis key %s error is %+v", redisKey, err)
			time.Sleep(5 * time.Second)
			continue
		}
	}
	log.Debugf("Fetched tokenPrice %f for tokenContract %s at blockHeight %d", tokenPriceAtHeight.Price, tokenContractAddr, blockHeight)
	return tokenPriceAtHeight.Price
}

func StoreV2TokensSummaryPayload(blockHeight int64) {
	key := fmt.Sprintf(REDIS_KEY_V2_TOKENS_SUMMARY_SNAPSHOT_AT_BLOCKHEIGHT, settingsObj.Development.Namespace, blockHeight)
	payload := make([]*TokenData, len(tokenList))
	var i int
	for _, tokenData := range tokenList {
		payload[i] = tokenData
		i += 1
	}
	tokenSummaryJson, err := json.Marshal(payload)
	if err != nil {
		log.Fatalf("Json marshal error %+v", err)
		return
	}
	for retryCount := 0; retryCount < 3; retryCount++ {
		res := redisClient.Set(key, string(tokenSummaryJson), 60*time.Minute) //TODO: Move to settings
		if res.Err() != nil {
			log.Errorf("Failed to add payload at blockHeight %d due to error %s, retrying %d", blockHeight, res.Err().Error(), retryCount)
			time.Sleep(5 * time.Second)
			continue
		}
		log.Debugf("Added payload at key %s", key)
		break
	}
}

func StoreTokenSummaryCIDInSnapshotsZSet(blockHeight int64, payloadCID string, txHash string) {
	key := fmt.Sprintf(REDIS_KEY_V2_TOKENS_SUMMARY_SNAPSHOTS_ZSET, settingsObj.Development.Namespace)
	var ZsetMember TokenSummarySnapshot
	ZsetMember.Cid = payloadCID
	ZsetMember.TxHash = txHash
	ZsetMemberJson, err := json.Marshal(ZsetMember)
	if err != nil {
		log.Fatalf("Json marshal error %+v", err)
		return
	}
	for retryCount := 0; retryCount < 3; retryCount++ {
		err := redisClient.ZAdd(key, redis.Z{
			Score:  float64(blockHeight),
			Member: ZsetMemberJson,
		}).Err()
		if err != nil {
			log.Errorf("Failed to add payloadCID %s at blockHeight %d due to error %+v, retrying %d", payloadCID, blockHeight, err, retryCount)
			time.Sleep(5 * time.Second)
			continue
		}
		log.Debugf("Added payloadCID %s at blockHeight %d successfully at key %s", payloadCID, blockHeight, key)
		break
	}
	PruneTokenSummarySnapshotsZSet()
}

func PruneTokenSummarySnapshotsZSet() {
	redisKey := fmt.Sprintf(REDIS_KEY_V2_TOKENS_SUMMARY_SNAPSHOTS_ZSET, settingsObj.Development.Namespace)
	res := redisClient.ZCard(redisKey)
	zsetLen := res.Val()
	log.Debugf("ZSet length is %d", zsetLen)
	if zsetLen > 20 {
		for retryCount := 0; retryCount < 3; retryCount++ {
			endRank := -1*(zsetLen-20) + 1
			log.Debugf("Removing entries in ZSet from rank %d to rank %d", 0, endRank)
			res = redisClient.ZRemRangeByRank(redisKey, 0, endRank)
			if res.Err() != nil {
				log.Error("Pruning entries at key:", redisKey, "failed with error:", res.Err().Error(), " , retrying ", retryCount)
				time.Sleep(5 * time.Second)
				continue
			}
			log.Debug("Pruning: Removed ", res.Val(), " entries in redis Zset at key:", redisKey)
			break
		}
	}
}

func CommitV2TokenSummaryPayload() error {
	url := settingsObj.Development.AuditProtocolEngine.URL + "/commit_payload"

	var apCommitResp AuditProtocolCommitPayloadResp
	var request AuditProtocolCommitPayloadReq
	request.ProjectId = fmt.Sprintf(V2_TOKENSUMMARY_PROJECTID, settingsObj.Development.Namespace)
	request.Payload.TokensData = make([]*TokenData, len(tokenList))
	request.Web3Storage = true //Always store TokenData snapshot in web3.storage.
	request.SkipAnchorProof = false
	var i int
	for _, tokenData := range tokenList {
		request.Payload.TokensData[i] = tokenData
		i += 1
	}
	body, err := json.Marshal(request)
	if err != nil {
		log.Fatalf("Failed to marshal request %+v towards Audit-Protocol with error %+v", request, err)
		return err
	}
	log.Debugf("URL %s. Committing Payload %s", url, string(body))
	retryCount := 0
	for ; retryCount < 3; retryCount++ {
		resp, err := apHttpClient.Post(url, "application/json", bytes.NewBuffer(body))
		if err != nil {
			log.Errorf("Error: Could not send commit-payload request to audit-protocol %+v due to error:", request, err)
			time.Sleep(5 * time.Second)
			continue
		}
		defer resp.Body.Close()
		body, err := ioutil.ReadAll(resp.Body)
		if err != nil {
			log.Error("Unable to read HTTP resp from Audit-protocol for commit-Payload.", err)
			time.Sleep(5 * time.Second)
			continue
		}
		log.Trace("Rsp Body", string(body))
		if resp.StatusCode == http.StatusOK {
			if err = json.Unmarshal(body, &apCommitResp); err != nil { // Parse []byte to the go struct pointer
				log.Errorf("Can not unmarshal JSON response received from Audit-protocol due to error %s, retrying %d",
					err, retryCount)
				continue
			}
			log.Debugf("Sucessfully committed payload to Audit-protocol at tentativeHeight %d with commitId %s",
				apCommitResp.TentativeHeight, apCommitResp.CommitID)
		} else {
			var errorResp AuditProtocolErrorResp
			if err = json.Unmarshal(body, &errorResp); err != nil {
				log.Errorf("Can not unmarshal error JSON response received from Audit-protocol due to error %s, retrying %d",
					err, retryCount)
				continue
			}
			log.Errorf("Received %d error on commit-payload with error data %+v, retrying %d",
				resp.StatusCode, errorResp, retryCount)
			continue
		}
		break
	}
	if retryCount >= 3 {
		return errors.New("failed to commit payload after max retries")
	}
	return nil
}

func FetchV2PairSummarySnapshot(blockHeight int64) []TokenPairLiquidityProcessedData {
	v2PairsProjectId := fmt.Sprintf(V2_PAIRSUMMARY_PROJECTID, settingsObj.Development.Namespace)
	last_block_height_url := fmt.Sprintf("%s/%s/payload/%d/data", settingsObj.Development.AuditProtocolEngine.URL, v2PairsProjectId, blockHeight)
	log.Debug("Fetching Blockheight URL:", last_block_height_url)
	var v2SummaryResp V2PairSummaryDataResp

	for retryCount := 0; retryCount < 3; retryCount++ {
		resp, err := apHttpClient.Get(last_block_height_url)
		if err != nil {
			log.Error("Error: Could not fetch block height for pairContract:", v2PairsProjectId, " Error:", err)
			time.Sleep(5 * time.Second)
			continue
		}
		defer resp.Body.Close()
		body, err := ioutil.ReadAll(resp.Body)
		if err != nil {
			log.Error("Unable to read HTTP resp.", err)
			return nil
		}
		log.Trace("Rsp Body", string(body))

		if resp.StatusCode != http.StatusOK {
			log.Error("Error: Got an error on audit-protocol side for projectID:", v2PairsProjectId, " with status code:", resp.StatusCode)
			time.Sleep(5 * time.Second)
			continue
		}

		if err = json.Unmarshal(body, &v2SummaryResp); err != nil { // Parse []byte to the go struct pointer
			log.Errorf("Can not unmarshal JSON due to error %+v", err)
			continue
		}
		break
	}
	log.Debugf("v2Pairs Summary data for projectID %s is : %+v", v2PairsProjectId, v2SummaryResp)
	if len(v2SummaryResp) > 0 {
		for _, val := range v2SummaryResp {
			return val.Payload.Data
		}
	}
	return nil
}

func WaitAndFetchBlockHeightStatus(blockHeight int64, retries int) (string, string, error) {
	projectID := fmt.Sprintf(V2_TOKENSUMMARY_PROJECTID, settingsObj.Development.Namespace)
	url := fmt.Sprintf("%s/%s/payload/%d/status", settingsObj.Development.AuditProtocolEngine.URL, projectID, blockHeight)
	log.Debug("Fetching CID at Blockheight URL:", url)

	var apResp AuditProtocolBlockHeightStatusResp
	var retryCount int
	for retryCount = 0; retryCount <= retries; retryCount++ {
		resp, err := apHttpClient.Get(url)
		if err != nil {
			log.Error("Error: Could not fetch block height for pairContract:", projectID, " Error:", err)
			time.Sleep(10 * time.Second)
			continue
		}
		defer resp.Body.Close()
		body, err := ioutil.ReadAll(resp.Body)
		if err != nil {
			log.Errorf("Unable to read HTTP resp due to error %+v , retrying %d", err, retryCount)
			time.Sleep(10 * time.Second)
			continue
		}
		log.Trace("Rsp Body", string(body))
		if resp.StatusCode == http.StatusBadRequest {
			log.Debugf("Snapshot for Block at height %d not yet ready, retrying %d", blockHeight, retryCount)
			time.Sleep(10 * time.Second)
			continue
		}
		if err = json.Unmarshal(body, &apResp); err != nil { // Parse []byte to the go struct pointer
			log.Errorf("Can not unmarshal JSON due to error %+v, retrying %d", err, retryCount)
			time.Sleep(10 * time.Second)
			continue
		}

		log.Debugf("Successfully received response  %+v for CID fetch for URL %s is", apResp, url)
		if apResp.Status < TX_CONFIRMATION_PENDING {
			log.Debugf("BlockHeight %d status is still pending %d. Retrying", blockHeight, apResp.Status)
			time.Sleep(10 * time.Second)
			continue
		}
		log.Debugf("Got CID %s, txHash %s at Block Height %d for projectID %s", apResp.PayloadCid, apResp.TxHash, blockHeight, projectID)
		return apResp.PayloadCid, apResp.TxHash, nil
	}

	log.Errorf("Max retries reached while trying to fetch payloadCID at height %d. Not retrying anymore.", blockHeight)
	return "", "", fmt.Errorf("max retries reached to fetch payloadCID at height %d", blockHeight)

}

func FetchV2SummaryLatestBlockHeight() int64 {
	v2PairsProjectId := fmt.Sprintf(V2_PAIRSUMMARY_PROJECTID, settingsObj.Development.Namespace)
	last_block_height_url := settingsObj.Development.AuditProtocolEngine.URL + "/" + v2PairsProjectId + "/payloads/height"
	log.Debug("Fetching Blockheight URL:", last_block_height_url)
	var heightResp AuditProtocolBlockHeightResp

	for retryCount := 0; retryCount < 3; retryCount++ {
		resp, err := apHttpClient.Get(last_block_height_url)
		if err != nil {
			log.Error("Error: Could not fetch block height for pairContract:", v2PairsProjectId, " Error:", err)
			time.Sleep(5 * time.Second)
			continue
		}
		defer resp.Body.Close()
		body, err := ioutil.ReadAll(resp.Body)
		if err != nil {
			log.Error("Unable to read HTTP resp.", err)
			return 0
		}
		log.Trace("Rsp Body", string(body))

		if err = json.Unmarshal(body, &heightResp); err != nil { // Parse []byte to the go struct pointer
			log.Errorf("Can not unmarshal JSON resp for due to error %+v", err)
			continue
		}
		break
	}
	log.Debugf("Last Block Height for projectID %s is : %d", v2PairsProjectId, heightResp.Height)
	return heightResp.Height
}

func PopulatePairContractList(pairContractAddr string) {
	if pairContractAddr != "" {
		log.Info("Skipping reading contract addresses from json.Considering only passed pairContractaddress:", pairContractAddr)
		pairContracts = make([]string, 1)
		pairContracts[0] = pairContractAddr
		return
	}

	log.Info("Reading contracts:", pairContractListFile)
	data, err := os.ReadFile(pairContractListFile)
	if err != nil {
		log.Error("Cannot read the file:", err)
		panic(err)
	}

	log.Debug("Contracts json data is", string(data))
	err = json.Unmarshal(data, &pairContracts)
	if err != nil {
		log.Error("Cannot unmarshal the pair-contracts json ", err)
		panic(err)
	}
}

func ReadSettings() {

	log.Info("Reading Settings:", settingsFile)
	data, err := os.ReadFile(settingsFile)
	if err != nil {
		log.Error("Cannot read the file:", err)
		panic(err)
	}

	log.Debug("Settings json data is", string(data))
	err = json.Unmarshal(data, &settingsObj)
	if err != nil {
		log.Error("Cannot unmarshal the settings json ", err)
		panic(err)
	}
	log.Info("Settings for namespace", settingsObj.Development.Namespace)
}

func SetupRedisClient() {
	redisURL := settingsObj.Development.Redis.Host + ":" + strconv.Itoa(settingsObj.Development.Redis.Port)

	log.Info("Connecting to redis at:", redisURL)
	redisClient = redis.NewClient(&redis.Options{
		Addr:     redisURL,
		Password: "",
		DB:       settingsObj.Development.Redis.Db,
	})
	pong, err := redisClient.Ping().Result()
	if err != nil {
		log.Error("Unable to connect to redis at:")
	}
	log.Info("Connected successfully to Redis and received ", pong, " back")
}

func InitAuditProtocolClient() {
	//TODO: Move these to settings

	t := http.Transport{
		//TLSClientConfig:    &tls.Config{KeyLogWriter: kl, InsecureSkipVerify: true},
		MaxIdleConns:        2,
		MaxConnsPerHost:     2,
		MaxIdleConnsPerHost: 2,
		IdleConnTimeout:     0,
		DisableCompression:  true,
	}

	apHttpClient = http.Client{
		Timeout:   10 * time.Second,
		Transport: &t,
	}

}
