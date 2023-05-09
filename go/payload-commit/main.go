package main

import (
	log "github.com/sirupsen/logrus"

	"pooler/caching"
	"pooler/goutils/ipfsutils"
	"pooler/goutils/logger"
	"pooler/goutils/redisutils"
	"pooler/goutils/settings"
	"pooler/goutils/smartcontract"
	taskmgr "pooler/goutils/taskmgr/rabbitmq"
	w3storage "pooler/goutils/w3s"
	"pooler/payload-commit/service"
	"pooler/payload-commit/worker"
)

func main() {
	logger.InitLogger()
	settingsObj := settings.ParseSettings()

	ipfsutils.InitClient(
		settingsObj.IpfsConfig.URL,
		settingsObj.PayloadCommit.Concurrency,
		settingsObj.IpfsConfig.IPFSRateLimiter,
		settingsObj.IpfsConfig.Timeout,
	)

	redisClient := redisutils.InitRedisClient(
		settingsObj.Redis.Host,
		settingsObj.Redis.Port,
		settingsObj.Redis.Db,
		20,
		settingsObj.Redis.Password,
		-1,
	)

	caching.NewRedisCache()
	smartcontract.InitContractAPI()
	taskmgr.NewRabbitmqTaskMgr()
	w3storage.InitW3S()
	caching.InitDiskCache()

	service.InitPayloadCommitService()

	mqWorker := worker.NewWorker()

	defer func() {
		mqWorker.ShutdownWorker()
		err := redisClient.Close()
		if err != nil {
			log.WithError(err).Error("error while closing redis client")
		}
	}()

	for {
		err := mqWorker.ConsumeTask()
		if err != nil {
			log.WithError(err).Error("error while consuming task, starting again")
		}
	}
}
