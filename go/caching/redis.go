package caching

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/go-redis/redis/v8"
	log "github.com/sirupsen/logrus"
	"github.com/swagftw/gi"

	"audit-protocol/goutils/datamodel"
	"audit-protocol/goutils/redisutils"
	"audit-protocol/token-aggregator/models"
)

type RedisCache struct {
	redisClient *redis.Client
}

var _ DbCache = (*RedisCache)(nil)

func NewRedisCache() *RedisCache {
	client, err := gi.Invoke[*redis.Client]()
	if err != nil {
		log.Fatal("Failed to invoke redis client", err)
	}

	cache := &RedisCache{redisClient: client}

	err = gi.Inject(cache)
	if err != nil {
		log.Fatal("Failed to inject redis cache", err)
	}

	return cache
}

func (r *RedisCache) GetLastProjectIndexedState(ctx context.Context) (map[string]*datamodel.ProjectIndexedState, error) {
	key := redisutils.REDIS_KEY_PROJECTS_INDEX_STATUS
	indexedStateMap := make(map[string]*datamodel.ProjectIndexedState)

	val, err := r.redisClient.HGetAll(ctx, key).Result()
	if err != nil {
		if err == redis.Nil {
			log.Errorf("error getting last project indexed state, key %s not found", key)

			return nil, ErrNotFound
		}

		return nil, ErrGettingProjects
	}

	for projectID, state := range val {
		indexedStateMap[projectID] = new(datamodel.ProjectIndexedState)

		err = json.Unmarshal([]byte(state), indexedStateMap[projectID])
		if err != nil {
			log.Errorf("error unmarshalling project indexed state for project %s", projectID)

			return nil, err
		}
	}

	return indexedStateMap, nil
}

func (r *RedisCache) GetPayloadCidAtEpochID(ctx context.Context, projectID string, dagHeight int) (string, error) {
	key := fmt.Sprintf(redisutils.REDIS_KEY_PROJECT_PAYLOAD_CIDS, projectID)
	payloadCid := ""
	height := strconv.Itoa(int(dagHeight))

	log.Debug("Geting PayloadCid from redis at key:", key, ",with height: ", dagHeight)

	res, err := r.redisClient.ZRangeByScoreWithScores(ctx, key, &redis.ZRangeBy{
		Min: height,
		Max: height,
	}).Result()
	if err != nil {
		log.Error("Could not Get payload cid from redis error: ", err)

		return "", err
	}

	log.Debug("Result for ZRangeByScoreWithScores : ", res)

	if len(res) == 1 {
		payloadCid = fmt.Sprintf("%v", res[0].Member)
	}

	log.Debugf("Geted %d Payload CIDs for key %s", len(res), key)

	return payloadCid, nil
}

// GetLastReportedDagHeight returns the last reported dag block height for the project
func (r *RedisCache) GetLastReportedDagHeight(ctx context.Context, projectID string) (int, error) {
	log.WithField("projectID", projectID)
	key := fmt.Sprintf(redisutils.REDIS_KEY_LAST_REPORTED_DAG_HEIGHT, projectID)

	val, err := r.redisClient.Get(ctx, key).Result()
	if err != nil {
		if err == redis.Nil {
			log.Errorf("error getting verification status, key %s not found", key)

			return 0, nil
		}

		return 0, ErrGettingLastDagVerificationStatus
	}

	height, err := strconv.Atoi(val)
	if err != nil {
		log.Errorf("error converting last verified height to int")

		return 0, ErrGettingLastDagVerificationStatus
	}

	return height, nil
}

// UpdateLastReportedDagHeight updates the last reported dag height for the project
func (r *RedisCache) UpdateLastReportedDagHeight(ctx context.Context, projectID string, dagHeight int) error {
	log.WithField("projectID", projectID)
	key := fmt.Sprintf(redisutils.REDIS_KEY_LAST_REPORTED_DAG_HEIGHT, projectID)

	_, err := r.redisClient.Set(ctx, key, dagHeight, 0).Result()

	return err
}

func (r *RedisCache) UpdateDagVerificationStatus(ctx context.Context, projectID string, status map[string][]*datamodel.DagVerifierStatus) error {
	log.WithField("projectID", projectID)
	key := fmt.Sprintf(redisutils.REDIS_KEY_DAG_VERIFICATION_STATUS, projectID)

	statusMap := make(map[string]string)
	for height, verifierStatus := range status {
		data, err := json.Marshal(verifierStatus)
		if err != nil {
			log.Errorf("error marshalling verification status for project %s", projectID)

			continue
		}
		statusMap[height] = string(data)
	}

	_, err := r.redisClient.HSet(ctx, key, statusMap).Result()
	if err != nil {
		log.Errorf("error updating last verified dag height for project %s", projectID)

		return err
	}

	return nil
}

func (r *RedisCache) GetProjectDAGBlockHeight(ctx context.Context, projectID string) (int, error) {
	// TODO implement me
	panic("implement me")
}

// UpdateDAGChainIssues updates the gaps in the dag chain for the project
func (r *RedisCache) UpdateDAGChainIssues(ctx context.Context, projectID string, dagChainIssues []*datamodel.DagChainIssue) error {
	key := fmt.Sprintf(redisutils.REDIS_KEY_PROJECT_DAG_CHAIN_GAPS, projectID)
	gaps := make([]*redis.Z, 0)

	l := log.WithField("projectID", projectID).WithField("dagChainIssues", dagChainIssues)

	for i := range dagChainIssues {
		gapStr, err := json.Marshal(dagChainIssues[i])
		if err != nil {
			l.WithError(err).Error("CRITICAL: failed to marshal dagChainIssue into json")
			continue
		}

		gaps = append(gaps, &redis.Z{Score: float64(dagChainIssues[i].DAGBlockHeight), Member: gapStr})
	}

	_, err := r.redisClient.ZAdd(ctx, key, gaps...).Result()
	if err != nil {
		l.WithError(err).Error("failed to update dagChainGaps into redis")

		return err
	}

	log.Infof("added %d DagGaps data successfully in redis for project: %s", len(dagChainIssues), projectID)

	return nil
}

// GetPayloadCIDs return the list of payloads cids for the project in given range
// startHeight and endHeight are string because they can be "-inf" or "+inf"
// -inf & +inf are just alias for start and end respectively, though the values must be changed according to cache implementation
func (r *RedisCache) GetPayloadCIDs(ctx context.Context, projectID string, startHeight, endHeight string) ([]*datamodel.DagBlock, error) {
	key := fmt.Sprintf(redisutils.REDIS_KEY_PROJECT_PAYLOAD_CIDS, projectID)

	log.
		WithField("key", key).
		Debug("fetching payload CIDs from redis")

	val, err := r.redisClient.ZRangeByScoreWithScores(ctx, key, &redis.ZRangeBy{
		Min: startHeight,
		Max: endHeight,
	}).Result()
	if err != nil {
		log.Error("Could not fetch payload CIDs error: ", err)

		return nil, err
	}

	dagChainBlocks := make([]*datamodel.DagBlock, len(val))

	for index, entry := range val {
		dagChainBlocks[index] = &datamodel.DagBlock{
			Data:   &datamodel.Data{PayloadLink: &datamodel.IPLDLink{Cid: fmt.Sprintf("%s", entry.Member)}},
			Height: int64(entry.Score),
		}
	}

	return dagChainBlocks, nil
}

// GetDagChainCIDs return the list of dag chain cids for the project in given range
// startHeight and endHeight are string because they can be "-inf" or "+inf"
// -inf & +inf are just alias for start and end respectively, though the values must be changed according to cache implementation
func (r *RedisCache) GetDagChainCIDs(ctx context.Context, projectID string, startHeight, endHeight string) ([]*datamodel.DagBlock, error) {
	key := fmt.Sprintf(redisutils.REDIS_KEY_PROJECT_CIDS, projectID)

	val, err := r.redisClient.ZRangeByScoreWithScores(ctx, key, &redis.ZRangeBy{
		Min: startHeight,
		Max: endHeight,
	}).Result()

	if err != nil {
		log.Error("Could not fetch entries error: ", err)

		return nil, err
	}

	dagChainBlocks := make([]*datamodel.DagBlock, len(val))

	for index, v := range val {
		dagChainBlocks[index] = &datamodel.DagBlock{
			CurrentCid: v.Member.(string),
			Height:     int64(v.Score),
		}
	}

	return dagChainBlocks, nil
}

// GetStoredProjects returns the list of projects that are stored in redis
func (r *RedisCache) GetStoredProjects(ctx context.Context) ([]string, error) {
	key := redisutils.REDIS_KEY_STORED_PROJECTS
	val, err := r.redisClient.SMembers(ctx, key).Result()
	if err != nil {
		if err == redis.Nil {
			log.Errorf("error getting stored projects, key %s not found", key)

			return []string{}, nil
		}

		return nil, ErrGettingProjects
	}

	return val, nil
}

func (r *RedisCache) StorePruningIssueReport(ctx context.Context, report *datamodel.PruningIssueReport) error {
	// TODO implement me
	panic("implement me")
}

func (r *RedisCache) GetPruningVerificationStatus(ctx context.Context) (map[string]*datamodel.ProjectPruningVerificationStatus, error) {
	// TODO implement me
	panic("implement me")
}

func (r *RedisCache) UpdatePruningVerificationStatus(ctx context.Context, projectID string, status *datamodel.ProjectPruningVerificationStatus) error {
	// TODO implement me
	panic("implement me")
}

func (r *RedisCache) GetProjectDagSegments(ctx context.Context, projectID string) (map[string]string, error) {
	// TODO implement me
	panic("implement me")
}

func (r *RedisCache) StoreReportedIssues(ctx context.Context, issue *datamodel.IssueReport) error {
	issueString, _ := json.Marshal(issue)

	res := r.redisClient.ZAdd(ctx, redisutils.REDIS_KEY_ISSUES_REPORTED, &redis.Z{Score: float64(time.Now().UnixMicro()), Member: issueString})

	if res.Err() != nil {
		log.Errorf("Failed to add issue to redis due to error %+v", res.Err())

		return res.Err()
	}

	return nil
}

func (r *RedisCache) RemoveOlderReportedIssues(ctx context.Context, tillTime int) error {
	err := r.redisClient.ZRemRangeByScore(ctx, redisutils.REDIS_KEY_ISSUES_REPORTED, "0", fmt.Sprintf("%d", tillTime)).Err()
	if err != nil {
		log.WithError(err).Errorf("Failed to remove older issues from redis due")

		return err
	}

	return nil
}

func (r *RedisCache) GetReportedIssues(ctx context.Context, projectID string) ([]*datamodel.IssueReport, error) {
	// TODO implement me
	panic("implement me")
}

func (r *RedisCache) FetchPairsSummaryLatestBlockHeight(ctx context.Context, poolerNamespace string) int64 {
	key := fmt.Sprintf(redisutils.REDIS_KEY_PAIRS_SUMMARY_SNAPSHOTS_ZSET, poolerNamespace)
	log.WithField("key", key).Debug("fetching latest available PairSummarySnapshot block height")

	val, err := r.redisClient.ZRangeWithScores(ctx, key, -1, -1).Result()
	if err != nil {
		log.WithError(err).Error("could not get latest block height for PairSummarySnapshot")

		return 0
	}

	if len(val) == 0 {
		log.Debug("no latest block height available for PairSummarySnapshot")

		return 0
	}

	blockHeight := int64(val[0].Score)
	log.WithField("blockHeight", blockHeight).Debug("latest available snapshot for PairSummarySnapshot is at height")

	return blockHeight
}

// FetchPairTokenMetadata fetches the token metadata for the given pair contract address
func (r *RedisCache) FetchPairTokenMetadata(ctx context.Context, poolerNamespace, pairContractAddr string) (*datamodel.TokenPairMetadata, error) {
	redisKey := fmt.Sprintf(redisutils.REDIS_KEY_TOKEN_PAIR_CONTRACT_TOKENS_DATA, poolerNamespace, pairContractAddr)
	log.WithField("key", redisKey).Debug("fetching PairContractTokensData from", redisKey)

	tokenPairMeta := new(datamodel.TokenPairMetadata)

	val, err := r.redisClient.HGetAll(ctx, redisKey).Result()
	if err != nil {
		log.WithError(err).Error("unable to fetch PairContractTokensData from redis")
	}

	log.Debug("fetched PairContractTokensData from redis")

	data, err := json.Marshal(val)
	if err != nil {
		log.WithError(err).Error("unable to marshal PairContractTokensData from redis")

		return nil, err
	}

	err = json.Unmarshal(data, tokenPairMeta)
	if err != nil {
		log.WithError(err).Error("unable to unmarshal PairContractTokensData from redis")

		return nil, err
	}

	return tokenPairMeta, nil
}

// FetchPairTokenAddresses fetches the token addresses for the given pair contract address
func (r *RedisCache) FetchPairTokenAddresses(ctx context.Context, poolerNamespace, pairContractAddr string) (*datamodel.TokenPairAddresses, error) {
	redisKey := fmt.Sprintf(redisutils.REDIS_KEY_PAIR_TOKEN_ADDRESSES, poolerNamespace, pairContractAddr)

	tokenContractAddresses, err := r.redisClient.HGetAll(ctx, redisKey).Result()
	if err != nil {
		log.WithField("key", redisKey).Error("failed to get PairContractTokensAddresses from redis")

		return nil, err
	}

	if len(tokenContractAddresses) == 0 {
		log.WithField("key", redisKey).Debug("no PairContractTokensAddresses found in redis")

		return nil, errors.New("pair token contract addresses not found in redis")
	}

	log.WithField("key", redisKey).Debug("fetched PairContractTokensAddresses from redis")

	addresses := new(datamodel.TokenPairAddresses)

	data, err := json.Marshal(tokenContractAddresses)
	if err != nil {
		log.WithError(err).Error("unable to marshal PairContractTokensAddresses from redis")

		return nil, err
	}

	err = json.Unmarshal(data, addresses)
	if err != nil {
		log.WithError(err).Error("unable to unmarshal PairContractTokensAddresses from redis")

		return nil, err
	}

	return addresses, nil
}

// FetchTokenSummaryLatestBlockHeight fetches the latest block height (tentative height) for the given project
func (r *RedisCache) FetchTokenSummaryLatestBlockHeight(ctx context.Context, poolerNamespace string) (int64, error) {
	key := fmt.Sprintf(redisutils.REDIS_KEY_TOKENS_SUMMARY_TENTATIVE_HEIGHT, poolerNamespace)

	val, err := r.redisClient.Get(ctx, key).Result()
	if err != nil {
		log.WithError(err).Errorf("could not fetch tentativeblock height error")

		return 0, err
	}

	tentativeHeight, err := strconv.Atoi(val)
	if err != nil {
		log.WithError(err).WithField("heightVal", val).Error("CRITICAL! unable to convert tentative block height to int")

		return 0, err
	}

	log.Debugf("fetched latest tentative block height for TokenSummary project")

	return int64(tentativeHeight), nil
}

// FetchPairSummarySnapshot fetches the token summary snapshot for the given block height
func (r *RedisCache) FetchPairSummarySnapshot(ctx context.Context, blockHeight int64, poolerNamespace string) ([]*models.TokenPairLiquidityProcessedData, error) {
	pairsSummarySnapshot := new(models.PairSummarySnapshot)
	key := fmt.Sprintf(redisutils.REDIS_KEY_PAIRS_SUMMARY_SNAPSHOT_BLOCKHEIGHT, poolerNamespace, blockHeight)

	log.WithField("key", key).Debugf("fetching latest PairSummary snapshot from redis key")

	val, err := r.redisClient.Get(ctx, key).Result()
	if err != nil {
		if errors.Is(err, redis.Nil) {
			log.Errorf("key %s not found in redis", key)

			return nil, err
		}

		log.WithError(err).Error("could not fetch latest PairSummary snapshot from redis")

		return nil, err
	}

	log.Tracef("Rsp Body %s", val)

	if err := json.Unmarshal([]byte(val), pairsSummarySnapshot); err != nil { // Parse []byte to the go struct pointer
		log.Errorf("Can not unmarshal JSON due to error %+v", err)

		return nil, err
	}

	log.WithField("snapshot", pairsSummarySnapshot).Debug("fetched summary snapshot from redis")

	return pairsSummarySnapshot.Data, nil
}

// FetchTokenPriceAtBlockHeight fetches the token price at the given block height
func (r *RedisCache) FetchTokenPriceAtBlockHeight(ctx context.Context, tokenContractAddr string, blockHeight int64, poolerNamespace string) (float64, error) {
	redisKey := fmt.Sprintf(redisutils.REDIS_KEY_TOKEN_BLOCK_HEIGHT_PRICE, poolerNamespace, tokenContractAddr)

	type tokenPriceAtBlockHeight struct {
		BlockHeight int     `json:"blockHeight"`
		Price       float64 `json:"price"`
	}

	tokenPriceAtHeight := new(tokenPriceAtBlockHeight)

	tokenPriceAtHeight.Price = 0

	zRangeByScore, err := r.redisClient.ZRangeByScore(ctx, redisKey, &redis.ZRangeBy{
		Min: fmt.Sprintf("%d", blockHeight),
		Max: fmt.Sprintf("%d", blockHeight),
	}).Result()

	if err != nil || len(zRangeByScore) == 0 {
		log.WithError(err).Errorf("failed to fetch tokenPrice for contract %s at blockHeight %d",
			tokenContractAddr, blockHeight)

		return 0, errors.New("failed to fetch tokenPrice from redis")
	}

	err = json.Unmarshal([]byte(zRangeByScore[0]), tokenPriceAtHeight)
	if err != nil {
		log.WithError(err).
			WithField("key", redisKey).
			Error("unable to parse tokenPrice retrieved from redis")

		return 0, err
	}

	log.Debugf("fetched tokenPrice %f for tokenContract %s at blockHeight %d", tokenPriceAtHeight.Price, tokenContractAddr, blockHeight)

	return tokenPriceAtHeight.Price, nil
}

// UpdateTokenPriceHistoryInRedis updates the token price history in redis
func (r *RedisCache) UpdateTokenPriceHistoryInRedis(ctx context.Context, toTime, fromTime float64, tokenData *models.TokenData, poolerNamespace string) error {
	key := fmt.Sprintf(redisutils.REDIS_KEY_TOKEN_PRICE_HISTORY, poolerNamespace, tokenData.ContractAddress)
	priceHistoryEntry := &models.TokenPriceHistory{Timestamp: toTime, Price: tokenData.Price, BlockHeight: tokenData.BlockHeight}

	val, err := json.Marshal(priceHistoryEntry)
	if err != nil {
		log.WithError(err).
			WithField("priceHistory", priceHistoryEntry).
			Error("Couldn't marshal json..something is really wrong with data.curTime:", toTime, " TokenData:", tokenData)

		return err
	}

	err = r.redisClient.ZAdd(ctx, key, &redis.Z{
		Score:  toTime,
		Member: string(val),
	}).Err()

	if err != nil {
		log.WithField("key", key).WithError(err).Error("failed to update price history in redis")

		return err
	}

	log.WithField("history", priceHistoryEntry).
		WithField("key", key).
		Debug("updated token price history")

	_ = r.PrunePriceHistoryInRedis(context.Background(), key, fromTime)

	return nil
}

// PrunePriceHistoryInRedis prunes the price history in redis
// remove any entries older than 1 hour from fromTime.
func (r *RedisCache) PrunePriceHistoryInRedis(ctx context.Context, key string, fromTime float64) error {
	res := r.redisClient.ZRemRangeByScore(ctx, key, fmt.Sprintf("%f", 0.0), fmt.Sprintf("%f", fromTime-60*60))

	if res.Err() != nil {
		log.WithField("key", key).
			Error("failed to prune price history in redis")
	}

	return nil
}

func (r *RedisCache) FetchTokenPriceHistoryInRedis(ctx context.Context, fromTime, toTime float64, contractAddress, poolerNamespace string) (*models.TokenPriceHistory, error) {
	key := fmt.Sprintf(redisutils.REDIS_KEY_TOKEN_PRICE_HISTORY, poolerNamespace, contractAddress)

	zRangeByScore, err := r.redisClient.ZRangeByScore(ctx, key, &redis.ZRangeBy{
		Min: fmt.Sprintf("%f", fromTime),
		Max: fmt.Sprintf("%f", toTime),
	}).Result()
	if err != nil {
		log.WithError(err).
			Error("failed to fetch token price history from redis")

		return nil, err
	}

	tokenPriceHistory := new(models.TokenPriceHistory)

	if len(zRangeByScore) == 0 {
		return nil, errors.New("no price history found")
	}

	err = json.Unmarshal([]byte(zRangeByScore[0]), tokenPriceHistory)
	if err != nil {
		log.WithError(err).
			WithField("priceHistory", zRangeByScore[0]).
			Error("unable to parse tokenPrice retrieved from redis")

		return nil, err
	}

	return tokenPriceHistory, nil
}

func (r *RedisCache) PruneTokenPriceZSet(ctx context.Context, tokenContractAddr string, blockHeight int64, poolerNamespace string) error {
	redisKey := fmt.Sprintf(redisutils.REDIS_KEY_TOKEN_BLOCK_HEIGHT_PRICE, poolerNamespace, tokenContractAddr)
	err := r.redisClient.ZRemRangeByScore(ctx,
		redisKey,
		"-inf",
		fmt.Sprintf("%d", blockHeight)).Err()

	if err != nil {
		log.WithError(err).Error("failed to pruned zset block height token price")
	}

	return nil
}

// FetchSummaryProjectSnapshots fetches the summary project snapshots from redis
func (r *RedisCache) FetchSummaryProjectSnapshots(ctx context.Context, key, min, max string) ([]*models.TokenSummarySnapshotMeta, error) {
	res, err := r.redisClient.ZRangeByScoreWithScores(ctx, key, &redis.ZRangeBy{Min: min, Max: max}).Result()
	if err != nil {
		if errors.Is(err, redis.Nil) {
			log.Infof("no entries found in snapshotsZSet")

			return nil, err
		}

		log.WithError(err).Errorf("failed to fetch entries from snapshotZSet")

		return nil, err
	}

	snapshots := make([]*models.TokenSummarySnapshotMeta, 0)

	for _, snapshot := range res {
		snapshotMeta := new(models.TokenSummarySnapshotMeta)

		err = json.Unmarshal([]byte(snapshot.Member.(string)), snapshotMeta)
		if err != nil {
			log.WithError(err).Errorf("failed to unmarshal snapshotMeta")

			return nil, err
		}

		snapshots = append(snapshots, snapshotMeta)
	}

	return snapshots, nil
}

func (r *RedisCache) RemoveOlderSnapshot(ctx context.Context, key string, snapshot *models.TokenSummarySnapshotMeta) error {
	byteData, _ := json.Marshal(snapshot)

	err := r.redisClient.ZRem(context.Background(), key, string(byteData)).Err()
	if err != nil {
		log.WithError(err).Error("failed to remove older snapshot")

		return err
	}

	return nil
}

func (r *RedisCache) AddSnapshot(ctx context.Context, key string, score int, snapshot *models.TokenSummarySnapshotMeta) error {
	err := r.redisClient.ZAdd(ctx, key, &redis.Z{
		Score:  float64(score),
		Member: snapshot,
	}).Err()

	if err != nil {
		log.WithError(err).Error("failed to add snapshot")

		return err
	}

	return nil
}

func (r *RedisCache) StoreTokensSummaryPayload(ctx context.Context, blockHeight int64, poolerNamespace string, tokenList map[string]*models.TokenData) error {
	key := fmt.Sprintf(redisutils.REDIS_KEY_TOKENS_SUMMARY_SNAPSHOT_AT_BLOCKHEIGHT, poolerNamespace, blockHeight)
	payload := make([]*models.TokenData, len(tokenList))

	var index int

	for _, tokenData := range tokenList {
		payload[index] = tokenData
		index += 1
	}

	tokenSummaryJson, err := json.Marshal(payload)
	if err != nil {
		log.WithError(err).Error("failed to marshal token summary payload")

		return err
	}

	res := r.redisClient.Set(ctx, key, string(tokenSummaryJson), 60*time.Minute) // TODO: Move to settings
	if res.Err() != nil {
		log.WithError(err).Error("failed to store token summary payload")

		return err
	}

	return nil
}

func (r *RedisCache) StoreTokenSummaryCIDInSnapshotsZSet(ctx context.Context, blockHeight int64, poolerNamespace string, tokenSummarySnapshotMeta *models.TokenSummarySnapshotMeta) error {
	key := fmt.Sprintf(redisutils.REDIS_KEY_TOKENS_SUMMARY_SNAPSHOTS_ZSET, poolerNamespace)

	zSetMemberJson, err := json.Marshal(tokenSummarySnapshotMeta)
	if err != nil {
		log.WithError(err).Error("failed to marshal token summary snapshot meta")

		return err
	}

	err = r.redisClient.ZAdd(ctx, key, &redis.Z{
		Score:  float64(blockHeight),
		Member: zSetMemberJson,
	}).Err()

	if err != nil {
		log.WithError(err).Error("failed to add token summary snapshot meta to zset")

		return err

	}

	err = r.PruneTokenSummarySnapshotsZSet(context.Background(), poolerNamespace)
	if err != nil {
		return err
	}

	return nil
}

func (r *RedisCache) PruneTokenSummarySnapshotsZSet(ctx context.Context, poolerNamespace string) error {
	redisKey := fmt.Sprintf(redisutils.REDIS_KEY_TOKENS_SUMMARY_SNAPSHOTS_ZSET, poolerNamespace)
	zSetLen, err := r.redisClient.ZCard(ctx, redisKey).Result()
	if err != nil {
		log.WithError(err).Error("failed to get length of token summary snapshots zset")

		return err
	}

	log.Debugf("ZSet length is %d", zSetLen)

	if zSetLen > 20 {
		endRank := -1*(zSetLen-20) + 1

		log.Debugf("Removing entries in ZSet from rank %d to rank %d", 0, endRank)

		err = r.redisClient.ZRemRangeByRank(ctx, redisKey, 0, endRank).Err()
		if err != nil {
			log.WithError(err).Error("Failed to prune token summary snapshots zset")

			return err
		}
	}

	return nil
}

func (r *RedisCache) CheckIfProjectExists(ctx context.Context, projectID string) (bool, error) {
	res, err := r.redisClient.Keys(ctx, fmt.Sprintf("projectID:%s:*", projectID)).Result()
	if err != nil {
		log.WithError(err).Error("failed to check if project exists")

		return false, err
	}

	if len(res) == 0 {
		return false, nil
	}

	return true, nil
}

func (r *RedisCache) GetTentativeBlockHeight(ctx context.Context, projectID string) (int, error) {
	res, err := r.redisClient.Get(ctx, fmt.Sprintf(redisutils.REDIS_KEY_PROJECT_TENTATIVE_BLOCK_HEIGHT, projectID)).Result()
	if err != nil {
		if errors.Is(err, redis.Nil) {
			return 0, nil
		}

		log.WithError(err).Error("failed to get tentative block height")

		return 0, err
	}

	blockHeight, err := strconv.Atoi(res)
	if err != nil {
		log.WithError(err).Error("failed to convert tentative block height to int")

		return 0, err
	}

	return blockHeight, nil
}

func (r *RedisCache) GetProjectEpochSize(ctx context.Context, id string) (int, error) {
	res, err := r.redisClient.Get(ctx, fmt.Sprintf(redisutils.REDIS_KEY_PROJECT_EPOCH_SIZE, id)).Result()
	if err != nil {
		if errors.Is(err, redis.Nil) {
			return 0, nil
		}

		log.WithError(err).Error("failed to get project epoch size")

		return 0, err
	}

	epochSize, err := strconv.Atoi(res)
	if err != nil {
		log.WithError(err).Error("failed to convert epoch size to int")

		return 0, err
	}

	return epochSize, nil
}

// StoreProjects stores the given projects in the redis cache
func (r *RedisCache) StoreProjects(background context.Context, projects []string) error {
	_, err := r.redisClient.SAdd(background, redisutils.REDIS_KEY_STORED_PROJECTS, projects).Result()

	if err != nil {
		log.WithError(err).Error("failed to store projects")

		return err
	}

	return nil
}

func (r *RedisCache) AddPayloadCID(ctx context.Context, projectID, payloadCID string, height float64) error {
	err := r.redisClient.ZAdd(ctx, fmt.Sprintf(redisutils.REDIS_KEY_PROJECT_PAYLOAD_CIDS, projectID), &redis.Z{
		Score:  height,
		Member: payloadCID,
	}).Err()

	if err != nil {
		log.WithError(err).Error("failed to add payload CID to zset")
	}

	return err
}

func (r *RedisCache) RemovePayloadCIDAtEpochID(ctx context.Context, projectID string, dagHeight int) error {
	err := r.redisClient.ZRemRangeByScore(ctx, fmt.Sprintf(redisutils.REDIS_KEY_PROJECT_PAYLOAD_CIDS, projectID), strconv.Itoa(dagHeight), strconv.Itoa(dagHeight)).Err()

	if err != nil {
		if err == redis.Nil {
			return nil
		}

		log.WithError(err).Error("failed to remove payload CID from zset")
	}

	return err
}

func (r *RedisCache) AddFinalizedPayload(background context.Context, projectID string, hash string, message json.RawMessage) error {
	_, err := r.redisClient.HSet(background, fmt.Sprintf(redisutils.REDIS_KEY_FINALIZED_INDEX_PAYLOAD, projectID), hash, string(message)).Result()

	if err != nil {
		log.WithError(err).Error("failed to add finalized payload to hash")

		return err
	}

	return nil
}

func (r *RedisCache) GetFinalizedIndexPayload(background context.Context, id string, hash string) (interface{}, error) {
	res, err := r.redisClient.HGet(background, fmt.Sprintf(redisutils.REDIS_KEY_FINALIZED_INDEX_PAYLOAD, id), hash).Result()
	if err != nil {
		log.WithError(err).Error("failed to get finalized payload")

		return nil, err
	}

	var payload map[string]interface{}

	err = json.Unmarshal([]byte(res), &payload)
	if err != nil {
		log.WithError(err).Error("failed to unmarshal finalized payload")

		return nil, err
	}

	return payload, nil
}
