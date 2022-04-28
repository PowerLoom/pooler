package main

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
	"net/http"
	"os"
	"strconv"
	"time"

	log "github.com/sirupsen/logrus"

	"github.com/ethereum/go-ethereum/common"

	"github.com/go-redis/redis"
)

var settingsObj ProjectSettings
var redisClient *redis.Client
var pairContracts []string
var tokenList map[string]TokenData

//var tokenPriceHistory map[int]float64

const settingsFile string = "../settings.json"
const pairContractListFile string = "../static/cached_pair_addresses.json"

//TODO: Move the below to config file.
const periodicRetrievalInterval time.Duration = 300 * time.Second

//const maxBlockCountToFetch int64 = 500 //Max number of blocks to fetch in 1 shot from Audit Protocol.

func main() {
	var pairContractAddressesFile string
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
	Run(pairContractAddressesFile)

}

func Run(pairContractAddress string) {
	for {

		PopulatePairContractList(pairContractAddress)

		t := time.Now()
		t2 := t.AddDate(0, 0, -1)
		time24h := float64(t2.Unix())
		//time24h = 0

		log.Debug("TimeStamp for 1 day before is:", time24h)
		//tokenPriceData := FetchV2TokenPriceDataFromRedis()
		//For now fetch all data within 24h for tradeVolume.
		//Optimization: If more tokenPairs are there, run this in parallel for different pairs.
		//In that case, need to colate data from the common data structures to where tokenData is updated, before writing to redis.
		tokenList := FetchTokenV2Data(time24h)
		if len(tokenList) == 0 {
			log.Info("No new blocks to fetch and process..Have to check in next cycle")
		} else {
			UpdateTokenDataToRedis(tokenList)
			//UpdateTokenCacheMetaDataToRedis(tokenCache)
		}

		log.Info("Sleeping for " + periodicRetrievalInterval.String() + " secs")
		time.Sleep(periodicRetrievalInterval)
	}
}

func FetchAndFillTokenMetaData(tokenList map[string]TokenData,
	pairContractAddr string) (TokenData, TokenData, error) {
	var token0Data, token1Data TokenData
	redisKey := fmt.Sprintf(REDIS_KEY_TOKEN_PAIR_CONTRACT_TOKENS_DATA, pairContractAddr)
	log.Debug("Fetching PariContractTokensData from redis with key:", redisKey)
	tokenPairMeta, err := redisClient.HGetAll(redisKey).Result()
	if err != nil {
		log.Error("Failed to get tokenPair MetaData from redis for PairContract:", pairContractAddr)
		return token0Data, token1Data, err
	}

	token0Sym := tokenPairMeta["token0_symbol"]
	log.Debug("Fetched tokenPairMetadata from redis:", tokenPairMeta, "token0:", tokenPairMeta["token0_symbol"])
	token0Data = tokenList[token0Sym]
	token0Data.Symbol = token0Sym
	token0Data.Name = tokenPairMeta["token0_name"]

	token1Sym := tokenPairMeta["token1_symbol"]
	token1Data = tokenList[token1Sym]
	token1Data.Symbol = token1Sym
	token1Data.Name = tokenPairMeta["token1_name"]

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
	log.Debug("Token0:", token0Data)
	log.Debug("Token1:", token1Data)
	return token0Data, token1Data, nil
}

/*func CalculateAndFillPriceChange(token0Data *TokenData, token1Data *TokenData) {

}*/
/*
func AggregateTokenTradeVolumeFromPair(lastBlockHeight int64, fromTime float64, pairContractAddress string,
	token0Data *TokenData, token1Data *TokenData) {
	toBlock := lastBlockHeight
	fromBlock := int64(1)
	/*lastAggregatedBlock := tokenPairCachedMetaData.LastAggregatedBlock.Height
	if lastAggregatedBlock == lastBlockHeight {
		//TODO: We cannot skip in this case, as we are aggregating fromTime data and data would become stale.
		//We need to keep moving the window and keep recalculating aggregatedDat by reducing it for that interval.
		log.Debug("As no additional blocks are created from last processing, refetching data to serve latest fromTime data.")

		*tokenPairCachedMetaData = TokenPairCacheMetaData{}
		//lastAggregatedBlock = 0
	}*/
/*tentativeNextBlockStartInterval := fromTime + periodicRetrievalInterval.Seconds()
toBlock := lastBlockHeight
fromBlock := lastBlockHeight
//Fetch this from cached data, as current tokenDataMap is being modified as we move ahead through each tokenPair.

tentativeStartAggregatedToken0Data := tokenPairCachedMetaData.TentativeNextStartAggregatedToken0Data
tentativeStartAggregatedToken1Data := tokenPairCachedMetaData.TentativeNextStartAggregatedToken1Data
lastAggregatedToken0Data := tokenPairCachedMetaData.LastAggregatedToken0Data
lastAggregatedToken1Data := tokenPairCachedMetaData.LastAggregatedToken1Data

tokenPairCachedMetaData.TentativeNextStartAggregatedToken0Data.TradeVolume_24h = 0
tokenPairCachedMetaData.TentativeNextStartAggregatedToken1Data.TradeVolume_24h = 0*/
/*There are below possible cases:
1. Started for firstTime and hence lastAggregatedBlock is 0.
   In this case, follow existing logic of fetching maxBlocks each time until we find blocks within specified fromTime.
2. There was a last fetch till which data has been aggregated.
   In this case, fetch only from lastAggregatedBlock to latestBlockHeight but maxBlocks in each fetch.
3. There was a last fetch till which data has been aggregated, but that timeInterval is older than fromTime.
	Fetch only till find blocks within specified fromTime, this will be greater than lastAggregatedBlock
*/

/*if lastAggregatedBlock != 0 {
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
	//hitTentativeNextBlockStart := false
	//TradeVolume and Liquidity for each pair: uniswap_pair_contract_V2_pair_data = 'uniswap:pairContract:'+settings.NAMESPACE+':{}:contractV2PairCachedData'
	//For now putting logic of going back each block till we get trade-Volume data..this needs to be fixed in Audit protocol.
	for {
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
				curIntervalLatestProcessedBlockInfo = DagBlockInfo{pairTradeVolume[0].Timestamp, pairTradeVolume[0].Height}
			}

			for j := range pairTradeVolume {
				if pairTradeVolume[j].Data.Payload.Timestamp > fromTime {
					//Use second aggregator to store data to be substracted for next interval.
					/*if pairTradeVolume[j].Data.Payload.Timestamp < tentativeNextBlockStartInterval {
						//Couldn't think of a better way to do this..under time constraints.
						if !hitTentativeNextBlockStart {
							hitTentativeNextBlockStart = true
							tokenPairCachedMetaData.TentativeNextIntervalBlockStart = DagBlockInfo{pairTradeVolume[j].Timestamp, pairTradeVolume[j].Height}
							log.Debug("TentativeNextBlockStart:", tokenPairCachedMetaData.TentativeNextIntervalBlockStart)
						}
						tokenPairCachedMetaData.TentativeNextStartAggregatedToken0Data.TradeVolume_24h += pairTradeVolume[j].Data.Payload.Token0TradeVolume
						tokenPairCachedMetaData.TentativeNextStartAggregatedToken1Data.TradeVolume_24h += pairTradeVolume[j].Data.Payload.Token1TradeVolume
					}
					count++
					token0Data.TradeVolume_24h += pairTradeVolume[j].Data.Payload.Token0TradeVolume
					token1Data.TradeVolume_24h += pairTradeVolume[j].Data.Payload.Token1TradeVolume
				} else {
					log.Debug("Hit older entries than", fromTime, ". Stop fetching further.")
					fromBlock = 1 //TODO: This is a dirty hack, need to improve.
					//tokenPairCachedMetaData.LastStartBlock = DagBlockInfo{pairTradeVolume[j].Timestamp, pairTradeVolume[j].Height}
					break
				}
			}
			log.Debug("Fetched ", len(pairTradeVolume), " entries. Found ", count, " entries in the tradeVolumePair from time:", fromTime)
		}
		if fromBlock == 1 {
			break
		}

		toBlock = fromBlock - 1
		blockRangeToFetch = toBlock - 1
		if blockRangeToFetch > maxBlockCountToFetch {
			fromBlock = toBlock - maxBlockCountToFetch
		} else {
			fromBlock = 1
		}
	}

	//Add previously aggregated fromTime data and substract previously aggregated data till tentativeBlockStart.
	/*token0Data.TradeVolume_24h += lastAggregatedToken0Data.TradeVolume_24h - tentativeStartAggregatedToken0Data.TradeVolume_24h
	token1Data.TradeVolume_24h += lastAggregatedToken1Data.TradeVolume_24h - tentativeStartAggregatedToken1Data.TradeVolume_24h

	//tokenPairCachedMetaData.LastAggregatedBlock = curIntervalLatestProcessedBlockInfo
	//tokenPairCachedMetaData.LastAggregatedToken0Data.TradeVolume_24h = token0Data.TradeVolume_24h
	//tokenPairCachedMetaData.LastAggregatedToken1Data.TradeVolume_24h = token1Data.TradeVolume_24h
	//log.Debug("PairCachedMetaData for this interval for tokenPair :", token0Data.Symbol, token1Data.Symbol, " is :", tokenPairCachedMetaData)
	log.Debug("TokenPair Data Aggregated for this interval:", pairContractAddress, " Token0Data:", token0Data, ", Token1Data:", token1Data)
}
*/

//TODO: Can we parallelize this for batches of contract pairs to make it faster?
//Need to evaluate load on Audit-protocol because of that.
func FetchTokenV2Data(fromTime float64) map[string]TokenData {
	tokenList = make(map[string]TokenData)
	//tentativeNextBlockStartInterval := fromTime + periodicRetrievalInterval.Seconds()
	log.Info("Number of pair contracts to process:", len(pairContracts)) //", tentativeNextBlockStartInterval", tentativeNextBlockStartInterval)
	//TODO: Add some retry logic and delay in between the loop and also for retries.
	//Look for something similar to Python's tenacity for Golang as well.

	for i := range pairContracts {
		pairContractAddress := pairContracts[i]
		//tokenPairCachedMetaData := tokenPairCachedMetaDataList[pairContractAddress]
		//log.Debug("PairCachedMetaData from previous interval is", tokenPairCachedMetaData)
		pairContractAddr := common.HexToAddress(pairContractAddress).Hex()

		// Get name and symbol of both tokens from
		//redis key uniswap:pairContract:UNISWAPV2:<pair-contract-address>:PairContractTokensData
		//TODO: Optimize: This fetch can be done once during init and whenver dynamic reload to re-read contract address pairs is implemented.
		var token0Data, token1Data TokenData
		var err error
		token0Data, token1Data, err = FetchAndFillTokenMetaData(tokenList, pairContractAddr)
		if err != nil {
			continue
		}
		//Calculate price change in last 24h
		//Get last 288th index price and substract it.
		//CalculateAndFillPriceChange(&token0Data, &token1Data)

		//Fetch Last block height.
		/*lastBlockHeight := FetchLastBlockHeight(strings.ToLower(pairContractAddress))
		if lastBlockHeight == 0 {
			log.Error("Skipping this pair as could not get blockheight")
			continue
		}*/

		// this is only for pair_total_reserves, because we want to capture latest reserves.
		//token0Liquidity, token1Liquidity, err := FetchLatestPairTotalReserves(strings.ToLower(pairContractAddress), int(lastBlockHeight), int(lastBlockHeight))
		tokenPairProcessedData, err := FetchLatestPairCachedDataFromRedis(pairContractAddr)
		if err != nil {
			//TODO: If this happens only for 1 pair..total liquidity will be skewed.Need to handle.
			log.Error("Not updating liquidity for this pairContract as..unable to fetch even after max retries.", pairContractAddress)
		} else {
			token0Data.Liquidity += tokenPairProcessedData.Token0Liquidity
			token1Data.Liquidity += tokenPairProcessedData.Token1Liquidity

			token0Data.TradeVolume_24h += tokenPairProcessedData.Token0TradeVolume_24h
			token1Data.TradeVolume_24h += tokenPairProcessedData.Token1TradeVolume_24h
			//Assuming that liquidity and tradeVolume for all tokenPairs is available at same height
			//hence taking the same from any pair should be fine.
			token0Data.Block_height_Liquidity = tokenPairProcessedData.Block_height_total_reserve
			token0Data.Block_height_trade_volume = tokenPairProcessedData.Block_height_trade_volume
			token1Data.Block_height_Liquidity = tokenPairProcessedData.Block_height_total_reserve
			token1Data.Block_height_trade_volume = tokenPairProcessedData.Block_height_trade_volume
		}

		//AggregateTokenTradeVolumeFromPair(lastBlockHeight, fromTime, pairContractAddress, &token0Data, &token1Data)*/

		//Update Map with latest  data.
		tokenList[token0Data.Symbol] = token0Data
		tokenList[token1Data.Symbol] = token1Data
		//tokenPairCachedMetaDataList[pairContractAddress] = tokenPairCachedMetaData
	}
	// Loop through all data and multiply liquidity and tradeVolume with TokenPrice
	//No need to multiplty with price as we are fetching cached data from redis which is already multiplied by price.
	for key, tokenData := range tokenList {
		if tokenData.Price != 0 {
			log.Debug("Token:", key, ".Multiplying liquidity with tokenPrice. Liquidity Before:", tokenData.Liquidity, ",TradeVolume_24h Before:", tokenData.TradeVolume_24h)
			tokenData.TradeVolume_24h *= tokenData.Price
			tokenData.Liquidity *= tokenData.Price
			//Update TokenPrice in History Zset
			UpdateTokenPriceHistoryRedis(fromTime, tokenData)
			CalculateAndFillPriceChange(fromTime, &tokenData)
			tokenList[key] = tokenData
			log.Debug("Token:", key, ".Multiplying liquidity with tokenPrice. Liquidity After:", tokenData.Liquidity, ",TradeVolume_24h After:", tokenData.TradeVolume_24h)

		} else {
			//Not resetting values in redis, hence it will reflect values 5 mins older.
			//TODO: Ideally, indicate staleness of data somehow so that User-exp is better on UI.
			log.Error("Price couldn't be retrieved for token:" + key + " hence removing token from the list.")
			delete(tokenList, key)
		}
	}
	return tokenList
}

func CalculateAndFillPriceChange(fromTime float64, tokenData *TokenData) {
	curTimeEpoch := float64(time.Now().Unix())
	key := fmt.Sprintf(REDIS_KEY_TOKEN_PRICE_HISTORY, settingsObj.Development.Namespace, tokenData.Symbol)

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

func UpdateTokenPriceHistoryRedis(fromTime float64, tokenData TokenData) {
	curTimeEpoch := float64(time.Now().Unix())
	key := fmt.Sprintf(REDIS_KEY_TOKEN_PRICE_HISTORY, settingsObj.Development.Namespace, tokenData.Symbol)
	var priceHistoryEntry TokenPriceHistoryEntry = TokenPriceHistoryEntry{curTimeEpoch, tokenData.Price}
	val, err := json.Marshal(priceHistoryEntry)
	if err != nil {
		log.Error("Couldn't marshal json..something is really wrong with data.curTime:", curTimeEpoch, " TokenData:", tokenData)
		return
	}
	err = redisClient.ZAdd(key, redis.Z{
		Score:  float64(curTimeEpoch),
		Member: string(val),
	}).Err()
	if err != nil {
		log.Error("Failed to add to redis ZSet, err:", err, " key :", key, ", Value:", val)
	}
	log.Debug("Updated TokenPriceHistory at Zset:", key, " with score:", curTimeEpoch, ",val:", priceHistoryEntry)
	//Need to prune history older than fromTime.
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

func FetchLatestPairCachedDataFromRedis(pairContractAddress string) (TokenPairLiquidityProcessedData, error) {
	var tokenPairCachedData TokenPairLiquidityProcessedData
	uniswap_pair_contract_V2_pair_data := fmt.Sprintf(REDIS_KEY_TOKEN_PAIR_V2_CACHED_DATA, settingsObj.Development.Namespace, pairContractAddress)
	log.Debug("Fetchin TokenPairContract Cached Data from Redis for:", uniswap_pair_contract_V2_pair_data)

	res := redisClient.Get(uniswap_pair_contract_V2_pair_data)
	if res.Err() != nil {
		log.Error("Unable to get TokenPairCachedData from Redis.")
		return tokenPairCachedData, res.Err()
	}
	bytes, _ := res.Bytes()
	if err := json.Unmarshal(bytes, &tokenPairCachedData); err != nil {
		log.Error("Can not unmarshal JSON. err", err, " payload:", bytes)
	}
	return tokenPairCachedData, nil
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
		keys[i] = fmt.Sprintf(REDIS_KEY_TOKEN_PAIR_V2_CACHED_PAIR_PRICE, settingsObj.Development.Namespace, tokenPairs[i])
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

/*func FetchV2CachedTokenDataFromRedis() map[string]TokenPairCacheMetaData {
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
}*/

func UpdateTokenDataToRedis(tokenList map[string]TokenData) {
	log.Info("Updating TokenData to redis for tokens count:", len(tokenList))
	for _, tokenData := range tokenList {
		tokenData.LastUpdatedTimeStamp = time.Now().String()
		redisKey := fmt.Sprintf(REDIS_KEY_TOKEN_CACHED_DATA, settingsObj.Development.Namespace, tokenData.Symbol)
		log.Debug("Updating Token Data for token:", tokenData.Symbol, " at key:", redisKey, " data:", tokenData)
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

/*func FetchPairTradeVolume(pairContractAddr string, fromHeight int, toHeight int) ([]TokenPairTradeVolumeData, error) {
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

func FetchLatestPairTotalReserves(pairContractAddr string, fromHeight int, toHeight int) (float64, float64, error) {
	pair_reserves_audit_project_id := "uniswap_pairContract_pair_total_reserves_" + pairContractAddr + "_" + settingsObj.Development.Namespace
	pair_reserves_range_fetch_url := settingsObj.Development.AuditProtocolEngine2.URL + "/" + pair_reserves_audit_project_id + "/payloads"
	var err error
	pairReserves := make([]TokenPairReserves, 0)

	for retryCount := 0; retryCount < 3; retryCount++ {
		pair_reserves_range_fetch_url += "?from_height=" + strconv.Itoa(fromHeight) + "&to_height=" + strconv.Itoa(toHeight) + "&data=true"
		log.Debug("Fetching TotalPair reserves at:", pair_reserves_range_fetch_url)

		resp, err := http.Get(pair_reserves_range_fetch_url)
		if err != nil {
			log.Error("Error: Could not fetch Pairtotal reserves for pairContract:", pairContractAddr, " Error:", err)
			time.Sleep(100 * time.Millisecond)
			continue
		}
		defer resp.Body.Close()
		body, err := ioutil.ReadAll(resp.Body)
		if err != nil {
			log.Error("Unable to read HTTP resp.", err)
			continue
		}
		log.Trace("Rsp Body", string(body))

		if err = json.Unmarshal(body, &pairReserves); err != nil { // Parse []byte to the go struct pointer
			log.Error("Can not unmarshal JSON. Resp.Body", string(body))
			continue
		}
		if err != nil && err.Error() == "Invalid Height" {
			toHeight--
			retryCount = 0
			continue
		}
		break
	}
	var token0Liquidity, token1Liquidity float64
	if err == nil {
		chainCurrentHeight := pairReserves[0].Data.Payload.ChainHeightRange.End
		// Fetch liquidity from the 0th index as we want the latest liquidity. data.payload.token0Reserves.block<height>
		// Had to convert uint to int..ideally this shouldn't cause any issue.
		liquidity, ok := pairReserves[0].Data.Payload.Token0Reserves["block"+strconv.Itoa(int(chainCurrentHeight))]
		if !ok {
			log.Error("Couldn't find latest block in pairTokenData for Token0,something wrong with snapshot.TODO")
		}
		token0Liquidity = liquidity

		liquidity, ok = pairReserves[0].Data.Payload.Token1Reserves["block"+strconv.Itoa(int(chainCurrentHeight))]
		if !ok {
			log.Error("Couldn't find latest block in pairTokenData for Token1,something wrong with snapshot.TODO")
		}
		log.Trace("Reserves[0]", pairReserves[0])
		token1Liquidity = liquidity
	}

	return token0Liquidity, token1Liquidity, err
}*/

func FetchLastBlockHeight(pairContractAddr string) int64 {
	pair_reserves_audit_project_id := "uniswap_pairContract_pair_total_reserves_" + pairContractAddr + "_" + settingsObj.Development.Namespace
	last_block_height_url := settingsObj.Development.AuditProtocolEngine2.URL + "/" + pair_reserves_audit_project_id + "/payloads/height"
	log.Debug("Fetching Blockheight URL:", last_block_height_url)
	var heightResp AuditProtocolBlockHeightResp

	for retryCount := 0; retryCount < 3; retryCount++ {
		resp, err := http.Get(last_block_height_url)
		if err != nil {
			log.Error("Error: Could not fetch block height for pairContract:", pairContractAddr, " Error:", err)
			time.Sleep(100 * time.Millisecond)
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
			log.Error("Can not unmarshal JSON")
			continue
		}
		break
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
