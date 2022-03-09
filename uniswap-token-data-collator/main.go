package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/ioutil"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	log "github.com/sirupsen/logrus"

	"github.com/ethereum/go-ethereum/common"

	"github.com/go-redis/redis"
)

var settingsObj ProjectSettings
var redisClient *redis.Client
var pairContracts []string
var tokenList map[string]TokenData

const settingsFile string = "../settings.json"
const pairContractListFile string = "../static/cached_pair_addresses.json"

//TODO: Move the below to config file.
const periodicRetrievalInterval time.Duration = 60 * time.Second
const maxBlockCountToFetch int64 = 500 //Max number of blocks to fetch in 1 shot from Audit Protocol.

func main() {
	var pairContractAddress string
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
		pairContractAddress = os.Args[2]
	}

	ReadSettings()
	SetupRedisClient()
	Run(pairContractAddress)

}

func Run(pairContractAddress string) {
	for {
		PopulatePairContractList(pairContractAddress)

		t := time.Now()
		t2 := t.AddDate(0, 0, -1)
		time24h := float64(t2.Unix())
		//time24h = 0

		log.Debug("TimeStamp for 1 day before is:", time24h)
		tokenCache := FetchV2CachedTokenDataFromRedis()
		//For now fetch all data within 24h for tradeVolume.
		//Optimization: If more tokenPairs are there, run this in parallel for different pairs.
		//In that case, need to colate data from the common data structures to where tokenData is updated, before writing to redis.
		tokenList := FetchTokenV2Data(time24h, tokenCache)
		if len(tokenList) == 0 {
			log.Error("No Tokens to fetch..Have to check in next cycle")
		} else {
			UpdateTokenDataToRedis(tokenList)
			UpdateTokenCacheMetaDataToRedis(tokenCache)
		}

		log.Info("Sleeping for " + periodicRetrievalInterval.String() + " secs")
		time.Sleep(periodicRetrievalInterval)
	}
}

//TODO: Can we parallelize this for batches of contract pairs to make it faster?
//Need to evaluate load on Audit-protocol because of that.
func FetchTokenV2Data(fromTime float64, tokenPairCachedMetaDataList map[string]TokenPairCacheMetaData) map[string]TokenData {
	tokenList = make(map[string]TokenData)
	log.Info("Number of pair contracts to process:", len(pairContracts))
	//TODO: Add some retry logic and delay in between the loop and also for retries.
	//Look for something similar to Python's tenacity for Golang as well.
	for i := range pairContracts {
		pairContractAddress := pairContracts[i]
		tokenPairCachedMetaData := tokenPairCachedMetaDataList[pairContractAddress]
		log.Debug("PairCachedMetaData is", tokenPairCachedMetaData)
		pairContractAddr := common.HexToAddress(pairContractAddress).Hex()

		// Get name and symbol of both tokens from
		//redis key uniswap:pairContract:UNISWAPV2:<pair-contract-address>:PairContractTokensData
		//TODO: This fetch can be done once during init and whenver dynamic reload to re-read contract address pairs is implemented.
		var token0Data, token1Data TokenData
		redisKey := "uniswap:pairContract:UNISWAPV2:" + pairContractAddr + ":PairContractTokensData"
		log.Debug("Fetching PariContractTokensData from redis with key:", redisKey)
		tokenPairMeta, err := redisClient.HGetAll(redisKey).Result()
		if err != nil {
			log.Error("Failed to get tokenPair MetaData from redis for PairContract:", pairContractAddr)
			continue
		}

		token0Sym := tokenPairMeta["token0_symbol"]
		log.Debug("Fetched tokenPairMetadata from redis:", tokenPairMeta, "token0:", tokenPairMeta["token0_symbol"])
		token0Data = tokenList[token0Sym]
		token0Data.Symbol = token0Sym
		token0Data.Name = tokenPairMeta["token0_name"]

		log.Debug("Token0:", token0Data)
		token1Sym := tokenPairMeta["token1_symbol"]
		token1Data = tokenList[token1Sym]
		token1Data.Symbol = token1Sym
		token1Data.Name = tokenPairMeta["token1_name"]

		//TODO: How to calculate price change?? to be fetched from 3rdParty.
		//Fetching from redis for now where price is stored against USDT for each token.
		if token0Data.Price == 0 || token1Data.Price == 0 {
			//Fetch token price against USDT for calculations.
			t0Price, t1Price := FetchTokenPairUSDTPriceFromRedis(token0Data.Symbol, token1Data.Symbol)
			if token0Data.Price == 0 && t0Price != 0 {
				token0Data.Price = t0Price
			}
			if token1Data.Price == 0 && t1Price != 0 {
				token1Data.Price = t1Price
			}
		}

		log.Debug("Token1:", token1Data)
		//Fetch block height.
		lastBlockHeight := FetchLastBlockHeight(strings.ToLower(pairContractAddress))
		if lastBlockHeight == 0 {
			log.Error("Skipping this pair as could not get blockheight")
		}
		toBlock := lastBlockHeight
		fromBlock := lastBlockHeight - 1 // this is only for pair_total_reserves.
		//Fetch this from cached data, as current tokenDataMap is being modified as we move ahead through each tokenPair.
		lastAggregatedBlock := tokenPairCachedMetaData.LastAggregatedBlock.Height
		if lastAggregatedBlock == lastBlockHeight {
			log.Debug("Skipping token Pair as no additional blocks are created from last processing.")
			continue
		}
		for {
			//Fetch pair_total_reserves from height-1 to this height
			pairReserves, err := FetchPairTotalReserves(strings.ToLower(pairContractAddress), int(fromBlock), int(toBlock))
			if err != nil {
				//Note: This is dependent on error string returned from Audit protocol and will break if that changes.
				if err.Error() == "Invalid Height" {
					toBlock--
					continue
				} /*else if err.Error() == "Internal Server Error" {

				}*/
				//TODO: Address failure to fetch. Should we retry? If so, how many times?
				log.Error("Skipping liquidity for pair contract", pairContractAddress)

			} else {
				chainCurrentHeight := pairReserves[0].Data.Payload.ChainHeightRange.End
				// Fetch liquidity from the 0th index as we want the latest liquidity. data.payload.token0Reserves.block<height>
				// Had to convert uint to int..ideally this shouldn't cause any issue.
				liquidity, ok := pairReserves[0].Data.Payload.Token0Reserves["block"+strconv.Itoa(int(chainCurrentHeight))]
				if !ok {
					log.Error("Couldn't find latest block in pairTokenData for Token0,something wrong with snapshot.TODO")
				}
				token0Data.Liquidity += liquidity

				liquidity, ok = pairReserves[0].Data.Payload.Token1Reserves["block"+strconv.Itoa(int(chainCurrentHeight))]
				if !ok {
					log.Error("Couldn't find latest block in pairTokenData for Token1,something wrong with snapshot.TODO")
				}
				token1Data.Liquidity += liquidity
			}
			break
		}

		//tentativeNextIntervalBlockStart := token0Data.MetaData.TentativeNextIntervalBlockStart.Number

		/*There are below possible cases:
		1. Started for firstTime and hence lastAggregatedBlock is 0.
		   In this case, follow existing logic of fetching maxBlocks each time until we find blocks within specified fromTime.
		2. There was a last fetch till which data has been aggregated.
		   In this case, fetch only from lastAggregatedBlock to latestBlockHeight but maxBlocks in each fetch.
		3. There was a last fetch till which data has been aggregated, but that timeInterval is older than fromTime.
			Fetch only till find blocks within specified fromTime, this will be greater than lastAggregatedBlock
		*/

		if lastAggregatedBlock != 0 {
			fromBlock = lastAggregatedBlock
		} else {
			fromBlock = 1
			lastAggregatedBlock = 1
		}

		blockRangeToFetch := toBlock - fromBlock
		if blockRangeToFetch > maxBlockCountToFetch {
			fromBlock = toBlock - maxBlockCountToFetch
		}

		curIntervalLatestProcessedBlockInfo := DagBlockInfo{0, 0}
		//For now putting logic of going back each block till we get trade-Volume data..this needs to be fixed in Audit protocol.
		for fromBlock >= lastAggregatedBlock {
		restartLoop:
			pairTradeVolume, err := FetchPairTradeVolume(strings.ToLower(pairContractAddress), int(fromBlock), int(toBlock))
			if err != nil {
				//Note: This is dependent on error string returned from Audit protocol and will break if that changes.
				if err.Error() == "Invalid Height" {
					toBlock--
					goto restartLoop
				} else if err.Error() == "Internal Server Error" {
					//Delay and retry.
					log.Error("Retrying due to Internal Server Error")
					time.Sleep(100 * time.Millisecond) //TODO: Need to make this some exponential backoff.
					goto restartLoop
				}
				log.Error("Skipping Trade-Volume for pair contract", pairContractAddress)

				break
			} else {
				count := 0
				//Update CurInterval Latest Block
				if pairTradeVolume[0].Height > curIntervalLatestProcessedBlockInfo.Height {
					curIntervalLatestProcessedBlockInfo = DagBlockInfo{float64(pairTradeVolume[0].Timestamp), pairTradeVolume[0].Height}
				}

				for j := range pairTradeVolume {
					if pairTradeVolume[j].Data.Payload.Timestamp > fromTime {
						count++
						token0Data.TradeVolume_24h += pairTradeVolume[j].Data.Payload.Token0TradeVolume
						token1Data.TradeVolume_24h += pairTradeVolume[j].Data.Payload.Token1TradeVolume
					} else {
						log.Debug("Hit older entries than", fromTime, ". Stop fetching further.")
						fromBlock = lastAggregatedBlock //TODO: This is a dirty hack, need to improve.
						break
					}
				}
				log.Debug("Fetched ", len(pairTradeVolume), " entries. Found ", count, " entries in the tradeVolumePair from time:", fromTime)
			}
			if fromBlock == lastAggregatedBlock {
				break
			}

			toBlock = fromBlock - 1
			blockRangeToFetch = toBlock - lastAggregatedBlock
			if blockRangeToFetch > maxBlockCountToFetch {
				fromBlock = toBlock - maxBlockCountToFetch
			} else {
				fromBlock = lastAggregatedBlock
			}
		}
		tokenPairCachedMetaData.LastAggregatedBlock = curIntervalLatestProcessedBlockInfo

		//Update Map with latest  data.
		tokenList[token0Sym] = token0Data
		tokenList[token1Sym] = token1Data
		tokenPairCachedMetaDataList[pairContractAddress] = tokenPairCachedMetaData
	}
	// Loop through all data and multiply liquidity and tradeVolume with TokenPrice
	for key, tokenData := range tokenList {
		if tokenData.Price != 0 {
			tokenData.TradeVolume_24h *= tokenData.Price
			tokenData.Liquidity *= tokenData.Price
		} else {
			//Not resetting values in redis, hence it will reflect values 5 mins older.
			//TODO: Ideally, indicate staleness of data somehow so that User-exp is better on UI.
			log.Error("Price couldn't be retrieved for token:" + key + " hence removing token from the list.")
			delete(tokenList, key)
		}
	}
	return tokenList
}

func FetchTokenPairUSDTPriceFromRedis(token0Sym string, token1Sym string) (float64, float64) {
	prices := FetchTokenPairCachedPriceFromRedis([]string{token0Sym + "-USDT", token1Sym + "-USDT"})

	//If price with USDT is not available, then fetch pairPrice with WETH and then convert to USDT.
	if prices[0] == 0 {
		wethPrices := FetchTokenPairCachedPriceFromRedis([]string{token0Sym + "-WETH", "WETH-USDT"})
		if wethPrices[0] == 0 {
			log.Error("Unable to fetch price  for token:", token0Sym, " with WETH")
		}
		prices[0] = wethPrices[0] * wethPrices[1]
	}

	if prices[1] == 0 {
		wethPrices := FetchTokenPairCachedPriceFromRedis([]string{token1Sym + "-WETH", "WETH-USDT"})
		if wethPrices[0] == 0 {
			log.Error("Unable to fetch price  for token:", token1Sym, " with WETH")
		}
		prices[1] = wethPrices[0] * wethPrices[1]
	}
	return prices[0], prices[1]
}

func FetchTokenPairCachedPriceFromRedis(tokenPairs []string) []float64 {
	keys := make([]string, len(tokenPairs))
	for i := range tokenPairs {
		keys[i] = "uniswap:pairContract:" + settingsObj.Development.Namespace + ":" + tokenPairs[i] + ":cachedPairPrice"
	}

	log.Debug("Fetching Token Price from redis for keys:", keys)
	res := redisClient.MGet(keys...)
	if res.Err() != nil {
		log.Error("Unable to get price info from Redis.")
		return make([]float64, len(tokenPairs))
	}
	values := res.Val()
	prices := make([]float64, len(tokenPairs))

	for i := range tokenPairs {
		var err error
		if values[i] != nil {
			tmpPrice := values[i].(string)
			if prices[i], err = strconv.ParseFloat(tmpPrice, 64); err == nil {
				log.Debug("Token ", i, " Price:", prices[i])
			}
		}
	}
	return prices
}

func FetchV2CachedTokenDataFromRedis() map[string]TokenPairCacheMetaData {
	keys := make([]string, len(pairContracts))
	for i := range pairContracts {
		keys[i] = "uniswap:tokenInfo:" + settingsObj.Development.Namespace + ":" + pairContracts[i] + ":cachedMetaData"
	}
	log.Info("Fetching TokenPairCacheMetaData from redis for all PairContracts Keys:", keys)

	res := redisClient.MGet(keys...)
	if res.Err() != nil {
		log.Error("Unable to get Cached Pair MetaData info from Redis.")
		//TODO: Fill map with empty objects and keys.
		return make(map[string]TokenPairCacheMetaData)
	}
	values := res.Val()
	tokenCacheMetaData := make(map[string]TokenPairCacheMetaData)
	var metaData TokenPairCacheMetaData

	for i := range values {
		if values[i] != nil {
			//log.Debug("Value interface from redis for TokenPairCacheMetaData", values[i])
			//Not checking for type conversion, as in any case it fails..new value of proper type will get overridden in redis.
			str := fmt.Sprintf("%v", values[i])
			if err := json.Unmarshal([]byte(str), &metaData); err != nil {
				log.Error("Can not unmarshal JSON. err", err, " payload:", str)
			}
			log.Debug("Value from redis for TokenPairCacheMetaData", metaData)
		}
		tokenCacheMetaData[pairContracts[i]] = metaData
	}
	log.Debug("Fetched TokenPairCacheMetaData from redis for all PairContracts.", tokenCacheMetaData)
	return tokenCacheMetaData
}

func UpdateTokenCacheMetaDataToRedis(tokenCachePairMetaData map[string]TokenPairCacheMetaData) {
	log.Info("Updating TokenCachePairMetaData to redis for tokenPairs count:", len(tokenCachePairMetaData))
	for key, tokenCacheData := range tokenCachePairMetaData {
		redisKey := "uniswap:tokenInfo:" + settingsObj.Development.Namespace + ":" + key + ":cachedMetaData"
		log.Debug("Updating Token Pair Cache Data for tokenPair:", key, " at key:", redisKey)
		jsonData, err := json.Marshal(tokenCacheData)
		if err != nil {
			log.Error("Json marshalling failed.")
		}
		err = redisClient.Set(redisKey, string(jsonData), 0).Err()
		if err != nil {
			log.Error("Storing TokenData: ", tokenCacheData, " to redis failed", err)
		}
	}
}

func UpdateTokenDataToRedis(tokenList map[string]TokenData) {
	log.Info("Updating TokenData to redis for tokens count:", len(tokenList))
	for _, tokenData := range tokenList {
		redisKey := "uniswap:tokenInfo:" + settingsObj.Development.Namespace + ":" + tokenData.Symbol + ":cachedData"
		log.Debug("Updating Token Data for token:", tokenData.Symbol, " at key:", redisKey)
		jsonData, err := json.Marshal(tokenData)
		if err != nil {
			log.Error("Json marshalling failed.")
		}
		err = redisClient.Set(redisKey, string(jsonData), 0).Err()
		if err != nil {
			log.Error("Storing TokenData: ", tokenData, " to redis failed", err)
		}
	}
}

func FetchPairTradeVolume(pairContractAddr string, fromHeight int, toHeight int) ([]TokenPairTradeVolumeData, error) {
	pair_trade_volume_audit_project_id := "uniswap_pairContract_trade_volume_" + pairContractAddr + "_" + settingsObj.Development.Namespace
	pair_volume_range_fetch_url := settingsObj.Development.AuditProtocolEngine2.URL + "/" + pair_trade_volume_audit_project_id + "/payloads"
	pair_volume_range_fetch_url += "?from_height=" + strconv.Itoa(fromHeight) + "&to_height=" + strconv.Itoa(toHeight) + "&data=true"

	log.Debug("Fetching TotalPair Trade Volume at:", pair_volume_range_fetch_url)
	resp, err := http.Get(pair_volume_range_fetch_url)
	if err != nil {
		log.Error("Error: Could not fetch Pairtotal Trade-Volume for pairContract:", pairContractAddr, " Error:", err)
		return nil, err
	}
	defer resp.Body.Close()

	body, err := ioutil.ReadAll(resp.Body)
	if err != nil {
		log.Println("Unable to read HTTP resp.", err)
		return nil, err
	}
	log.Trace("Rsp Body", string(body))
	var pairVolumes []TokenPairTradeVolumeData
	if err = json.Unmarshal(body, &pairVolumes); err != nil { // Parse []byte to the go struct pointer
		var errResp AuditProtocolErrorResp
		if err = json.Unmarshal(body, &errResp); err != nil {
			log.Error("Can not unmarshal JSON. Resp.Body", string(body))
			return nil, err
		} else {
			return nil, errors.New(errResp.Error)
		}

	}
	return pairVolumes, err
}

func FetchPairTotalReserves(pairContractAddr string, fromHeight int, toHeight int) ([]TokenPairReserves, error) {
	pair_reserves_audit_project_id := "uniswap_pairContract_pair_total_reserves_" + pairContractAddr + "_" + settingsObj.Development.Namespace
	pair_reserves_range_fetch_url := settingsObj.Development.AuditProtocolEngine2.URL + "/" + pair_reserves_audit_project_id + "/payloads"

	pairReserves := make([]TokenPairReserves, 0)

	pair_reserves_range_fetch_url += "?from_height=" + strconv.Itoa(fromHeight) + "&to_height=" + strconv.Itoa(toHeight) + "&data=true"
	log.Debug("Fetching TotalPair reserves at:", pair_reserves_range_fetch_url)
	resp, err := http.Get(pair_reserves_range_fetch_url)
	if err != nil {
		log.Error("Error: Could not fetch Pairtotal reserves for pairContract:", pairContractAddr, " Error:", err)
		return nil, err
	}
	defer resp.Body.Close()
	body, err := ioutil.ReadAll(resp.Body)
	if err != nil {
		log.Error("Unable to read HTTP resp.", err)
		return nil, err
	}
	log.Trace("Rsp Body", string(body))

	if err = json.Unmarshal(body, &pairReserves); err != nil { // Parse []byte to the go struct pointer
		log.Error("Can not unmarshal JSON. Resp.Body", string(body))
		//TODO: Build retry logic with some delay to take care of internal error.
		return nil, err
	}
	log.Trace("Reserves[0]", pairReserves[0])
	return pairReserves, err
}

func FetchLastBlockHeight(pairContractAddr string) int64 {
	pair_reserves_audit_project_id := "uniswap_pairContract_pair_total_reserves_" + pairContractAddr + "_" + settingsObj.Development.Namespace
	last_block_height_url := settingsObj.Development.AuditProtocolEngine2.URL + "/" + pair_reserves_audit_project_id + "/payloads/height"
	log.Debug("Fetching Blockheight URL:", last_block_height_url)
	resp, err := http.Get(last_block_height_url)
	if err != nil {
		log.Error("Error: Could not fetch block height for pairContract:", pairContractAddr, " Error:", err)
	}
	defer resp.Body.Close()
	body, err := ioutil.ReadAll(resp.Body)
	if err != nil {
		log.Error("Unable to read HTTP resp.", err)
		return 0
	}
	log.Trace("Rsp Body", string(body))

	var heightResp AuditProtocolBlockHeightResp
	if err = json.Unmarshal(body, &heightResp); err != nil { // Parse []byte to the go struct pointer
		log.Error("Can not unmarshal JSON")
	}
	log.Debug("Last Block Height is:", heightResp)
	return heightResp.Height
}

func PopulatePairContractList(pairContractAddr string) {
	if pairContractAddr != "" {
		log.Info("Skipping reading contract addresses from json.\nConsidering only passed pairContractaddress:", pairContractAddr)
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
