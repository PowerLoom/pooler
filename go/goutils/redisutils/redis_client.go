package redisutils

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/swagftw/gi"

	"audit-protocol/goutils/datamodel"

	"github.com/go-redis/redis/v8"
	log "github.com/sirupsen/logrus"
)

func InitRedisClient(redisHost string, port int, redisDb int, poolSize int, password string, timeout time.Duration) *redis.Client {
	redisURL := redisHost + ":" + strconv.Itoa(port)

	log.Info("Connecting to redis at:", redisURL)
	redisClient := redis.NewClient(&redis.Options{
		Addr:        redisURL,
		Password:    password,
		DB:          redisDb,
		PoolSize:    poolSize,
		ReadTimeout: timeout,
	})
	pong, err := redisClient.Ping(context.Background()).Result()
	if err != nil {
		log.WithField("addr", redisURL).Fatal("Unable to connect to redis")
	}

	log.Info("Connected successfully to Redis and received ", pong, " back")

	// exit if injection fails
	err = gi.Inject(redisClient)
	if err != nil {
		log.Fatalln("Failed to inject redis client", err)
	}

	return redisClient
}

func FetchStoredProjects(ctx context.Context, redisClient *redis.Client, retryCount int) []string {
	key := REDIS_KEY_STORED_PROJECTS
	log.Debugf("Fetching stored Projects from redis at key: %s", key)
	for i := 0; i < retryCount; i++ {
		res := redisClient.SMembers(ctx, key)
		if res.Err() != nil {
			if res.Err() == redis.Nil {
				log.Infof("Stored Projects key doesn't exist..retrying")
				time.Sleep(5 * time.Minute)
				continue
			}
			log.Errorf("Failed to fetch stored projects from redis due to err %+v. Retrying %d", res.Err(), i)
			time.Sleep(5 * time.Second)
			continue
		}
		log.Infof("Retrieved %d storedProjects %+v from redis", len(res.Val()), res.Val())
		return res.Val()
	}
	return nil
}

func SetIntFieldInRedis(ctx context.Context, redisClient *redis.Client, key string, value int,
	retryIntervalsecs int, retrycount int) bool {
	for j := 0; j <= retrycount; j++ {
		resSet := redisClient.Set(ctx, key, strconv.Itoa(value), 0)
		if resSet.Err() != nil {
			log.Errorf("Failed to set key %s due to error %+v", key, resSet.Err())
			time.Sleep(time.Duration(retryIntervalsecs) * time.Second)
			j++
			continue
		}
		log.Debugf("Set key %s with value %d successfully in redis", key, value)
		return true
	}
	return false
}

/*
Returns the following:

	value : in case of success
	-1    : in case of failure
	 0     : if key not exist.
*/
func FetchIntFieldFromRedis(ctx context.Context, redisClient *redis.Client, key string,
	retryIntervalsecs int, retrycount int) int {
	for i := 0; i <= retrycount; i++ {
		res := redisClient.Get(ctx, key)
		if res.Err() == redis.Nil {
			log.Debugf("Key %s not present in redis", key)
			return 0
		} else if res.Err() != nil {
			log.Errorf("Failed to fetch key %s due to error %+v", key, res.Err())
			time.Sleep(time.Duration(retryIntervalsecs) * time.Second)
			i++
			continue
		}
		value, err := strconv.Atoi(res.Val())
		if err != nil {
			log.Fatalf("Failed to convert int value fetched from redis key %s due to error %+v", key, err)
			return -1
		}
		log.Debugf("Fetched key %s from redis with value %d", key, value)
		return value
	}
	return -1
}

func GetPayloadCidFromZSet(ctx context.Context, redisClient *redis.Client, projectId string, startScore string,
	retryIntervalsecs int, retrycount int) (string, error) {
	//key := projectId + ":payloadCids"
	key := fmt.Sprintf(REDIS_KEY_PROJECT_PAYLOAD_CIDS, projectId)
	payloadCid := ""

	log.Debug("Fetching PayloadCid from redis at key:", key, ",with startScore: ", startScore)
	for i := 0; ; {
		zRangeByScore := redisClient.ZRangeByScoreWithScores(ctx, key, &redis.ZRangeBy{
			Min: startScore,
			Max: startScore,
		})

		err := zRangeByScore.Err()
		log.Debug("Result for ZRangeByScoreWithScores : ", zRangeByScore)
		if err != nil {
			log.Errorf("Could not fetch PayloadCid from  redis for project %s at blockHeight %d error: %+v Query: %+v",
				projectId, startScore, err, zRangeByScore)
			if i == retrycount {
				log.Errorf("Could not fetch PayloadCid from  redis after max retries for project %s at blockHeight %d error: %+v Query: %+v",
					projectId, startScore, err, zRangeByScore)
				return "", err
			}
			i++
			time.Sleep(time.Duration(retryIntervalsecs) * time.Second)
			continue
		}

		res := zRangeByScore.Val()

		log.Debugf("Fetched %d Payload CIDs for key %s", len(res), key)
		if len(res) == 1 {
			payloadCid = fmt.Sprintf("%v", res[0].Member)
			log.Debugf("PayloadLink %s fetched for project %s at height %s from redis", payloadCid, projectId, startScore)
		} else if len(res) > 1 {
			log.Errorf("Found more than 1 payload CIDS at height %d for project %s which means project state is messed up due to an issue that has occured while previous snapshot processing, considering the first one so that current snapshot processing can proceed",
				startScore, projectId)
			payloadCid = fmt.Sprintf("%v", res[0].Member)
		}
		break
	}
	return payloadCid, nil
}

func AddPayloadCidToZSet(ctx context.Context, redisClient *redis.Client,
	payload *datamodel.PayloadCommit, retryIntervalsecs int, retrycount int) error {
	for retryCount := 0; ; {
		key := fmt.Sprintf(REDIS_KEY_PROJECT_PAYLOAD_CIDS, payload.ProjectId)
		res := redisClient.ZAdd(ctx, key,
			&redis.Z{
				Score:  float64(payload.TentativeBlockHeight),
				Member: payload.SnapshotCID,
			})
		if res.Err() != nil {
			if retryCount == retrycount {
				log.Errorf("Failed to Add payload %s to redis Zset with key %s after max-retries of %d", payload.SnapshotCID, key, retrycount)
				return res.Err()
			}
			time.Sleep(time.Duration(retryIntervalsecs) * time.Second)
			retryCount++
			log.Errorf("Failed to Add payload %s to redis Zset with key %s..retryCount %d", payload.SnapshotCID, key, retryCount)
			continue
		}
		log.Debugf("Added payload %s to redis Zset with key %s successfully", payload.SnapshotCID, key)
		break
	}
	return nil
}
