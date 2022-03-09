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

var settings ProjectSettings
var redisClient *redis.Client
var pairContracts []string
var tokenList map[string]TokenData

const settingsFile string = "../settings.json"
const pairContractList string = "../static/cached_pair_addresses.json"

//TODO: Move the below to config file.
const periodicRetrievalInterval time.Duration = 300 * time.Second
const maxBlockCountToFetch int = 500 //Max number of blocks to fetch in 1 shot from Audit Protocol.

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
		//For now fetch all data within 24h for tradeVolume.
		tokenList := FetchTokenV2Data(1, -1, time24h)
		if len(tokenList) == 0 {
			log.Error("No Tokens to fetch..Have to check in next cycle")
		} else {
			UpdateTokenDataToRedis(tokenList)
		}

		log.Info("Sleeping for " + periodicRetrievalInterval.String() + " secs")
		time.Sleep(periodicRetrievalInterval)
	}
}

func FetchTokenV2Data(fromBlock int, toBlock int, fromTime float64) map[string]TokenData {
	tokenList = make(map[string]TokenData)
	log.Info("Number of pair contracts to process:", len(pairContracts))

	for i := range pairContracts {
		pairContractAddress := pairContracts[i]
		pairContractAddr := common.HexToAddress(pairContractAddress).Hex()

		// Get name and symbol of both tokens from
		//redis key uniswap:pairContract:UNISWAPV2:<pair-contract-address>:PairContractTokensData
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

		//TODO: How to calculate price change?? Need to come up with an approach for this to store priceHistory and then calculate to be reported.
		//Fetching from redis for now where price is stored against USDT for each token.
		if token0Data.Price == 0 || token1Data.Price == 0 {
			t0Price, t1Price := FetchTokenPairUSDTPriceFromRedis(token0Data.Symbol, token1Data.Symbol, pairContractAddr)
			if token0Data.Price == 0 && t0Price != 0 {
				token0Data.Price = t0Price
			}
			if token1Data.Price == 0 && t1Price != 0 {
				token1Data.Price = t1Price
			}
			if token0Data.Price == 0 {
				log.Error("unable to retrieve price from redis for token:", token0Data)
			}
			if token1Data.Price == 0 {
				log.Error("unable to retrieve price from redis for token:", token1Data)
			}
		}

		log.Debug("Token1:", token1Data)
		//Fetch block height.
		lastBlockHeight := fetchLastBlockHeight(strings.ToLower(pairContractAddress))
		if lastBlockHeight == 0 {
			log.Error("Skipping this pair as could not get blockheight")
		}
		toBlock := lastBlockHeight
		fromBlock := lastBlockHeight - 1 // this is only for pair_total_reserves.

		for {
			//Fetch pair_total_reserves from height-1 to this height
			pairReserves, err := fetchPairTotalReserves(strings.ToLower(pairContractAddress), int(fromBlock), int(toBlock))
			if err != nil {
				//Note: This is dependent on error string returned from Audit protocol and will break if that changes.
				if err.Error() == "Invalid Height" {
					toBlock--
					continue
				}
				//TODO: Address failure to fetch.
				log.Error("Skipping liquidity for pair contract", pairContractAddress)
				//break
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

		blockDiff := toBlock - maxBlockCountToFetch
		if blockDiff < 1 {
			fromBlock = 1
		} else {
			fromBlock = blockDiff
		}

		//For now putting logic of going back each block till we get trade-Volume data..this needs to be fixed in Audit protocol.
		for fromBlock >= 1 {
		restartLoop:
			pairTradeVolume, err := fetchPairTradeVolume(strings.ToLower(pairContractAddress), int(fromBlock), int(toBlock))
			if err != nil {
				//Note: This is dependent on error string returned from Audit protocol and will break if that changes.
				if err.Error() == "Invalid Height" {
					toBlock--
					goto restartLoop
				}
				log.Error("Skipping Trade-Volume for pair contract", pairContractAddress)
			} else {
				count := 0
				for j := range pairTradeVolume {
					if pairTradeVolume[j].Data.Payload.Timestamp > fromTime {
						count++
						token0Data.TradeVolume_24h += pairTradeVolume[j].Data.Payload.Token0TradeVolume
						token1Data.TradeVolume_24h += pairTradeVolume[j].Data.Payload.Token1TradeVolume
					}
				}
				log.Debug("Fetched ", len(pairTradeVolume), " entries. Found ", count, " entries in the tradeVolumePair from time:", fromTime)
			}
			if fromBlock == 1 {
				break
			}
			blockDiff := fromBlock - maxBlockCountToFetch
			toBlock = fromBlock - 1
			if blockDiff < 1 {
				fromBlock = 1
			} else {
				fromBlock = blockDiff
			}
		}
		//Update Map with latest  data.
		tokenList[token0Sym] = token0Data
		tokenList[token1Sym] = token1Data
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

func FetchTokenPairUSDTPriceFromRedis(token0Sym string, token1Sym string, pairContractAddr string) (float64, float64) {
	token0Key := "uniswap:pairContract:" + settings.Development.Namespace + ":" + token0Sym + "-USDT:cachedPairPrice"
	token1Key := "uniswap:pairContract:" + settings.Development.Namespace + ":" + token1Sym + "-USDT:cachedPairPrice"
	keys := []string{token0Key, token1Key}
	log.Debug("Fetching Token Price from redis for keys:", keys)
	res := redisClient.MGet(keys...)
	if res.Err() != nil {
		log.Error("Unable to get price info from Redis.")
		return 0, 0
	}
	values := res.Val()
	var token0Price, token1Price float64
	var err error
	if values[0] != nil {
		t0Price := values[0].(string)
		if token0Price, err = strconv.ParseFloat(t0Price, 64); err == nil {
			log.Debug("Token0 Price:", token0Price)
		}
	}

	if values[1] != nil {
		t1Price := values[1].(string)
		if token1Price, err = strconv.ParseFloat(t1Price, 64); err == nil {
			log.Debug("Token1 Price:", token1Price)
		}
	}

	return token0Price, token1Price
}

func UpdateTokenDataToRedis(tokenList map[string]TokenData) {
	log.Info("Updating TokenData to redis for tokens count:", len(tokenList))
	for _, tokenData := range tokenList {
		redisKey := "uniswap:tokenInfo:" + settings.Development.Namespace + ":" + tokenData.Symbol + ":cachedData"
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

func fetchPairTradeVolume(pairContractAddr string, fromHeight int, toHeight int) ([]TokenPairTradeVolumeData, error) {
	pair_trade_volume_audit_project_id := "uniswap_pairContract_trade_volume_" + pairContractAddr + "_" + settings.Development.Namespace
	pair_volume_range_fetch_url := settings.Development.AuditProtocolEngine2.URL + "/" + pair_trade_volume_audit_project_id + "/payloads"
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

func fetchPairTotalReserves(pairContractAddr string, fromHeight int, toHeight int) ([]TokenPairReserves, error) {
	pair_reserves_audit_project_id := "uniswap_pairContract_pair_total_reserves_" + pairContractAddr + "_" + settings.Development.Namespace
	pair_reserves_range_fetch_url := settings.Development.AuditProtocolEngine2.URL + "/" + pair_reserves_audit_project_id + "/payloads"

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
		return nil, err
	}
	log.Trace("Reserves[0]", pairReserves[0])
	return pairReserves, err
}

func fetchLastBlockHeight(pairContractAddr string) int {
	pair_reserves_audit_project_id := "uniswap_pairContract_pair_total_reserves_" + pairContractAddr + "_" + settings.Development.Namespace
	last_block_height_url := settings.Development.AuditProtocolEngine2.URL + "/" + pair_reserves_audit_project_id + "/payloads/height"
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

	log.Info("Reading contracts:", pairContractList)
	data, err := os.ReadFile(pairContractList)
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
	err = json.Unmarshal(data, &settings)
	if err != nil {
		log.Error("Cannot unmarshal the settings json ", err)
		panic(err)
	}
	log.Info("Settings for namespace", settings.Development.Namespace)
}

func SetupRedisClient() {
	redisURL := settings.Development.Redis.Host + ":" + strconv.Itoa(settings.Development.Redis.Port)

	log.Info("Connecting to redis at:", redisURL)
	redisClient = redis.NewClient(&redis.Options{
		Addr:     redisURL,
		Password: "",
		DB:       settings.Development.Redis.Db,
	})
	pong, err := redisClient.Ping().Result()
	if err != nil {
		log.Error("Unable to connect to redis at:")
	}
	log.Info("Connected successfully to Redis and received ", pong, " back")
}
