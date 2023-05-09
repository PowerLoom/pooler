package service

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"

	"github.com/cenkalti/backoff/v4"
	"github.com/ethereum/go-ethereum/accounts/abi/bind"
	"github.com/ethereum/go-ethereum/ethclient"
	"github.com/ethereum/go-ethereum/signer/core/apitypes"
	"github.com/hashicorp/go-retryablehttp"
	log "github.com/sirupsen/logrus"
	"github.com/swagftw/gi"

	"pooler/caching"
	datamodel2 "pooler/goutils/datamodel"
	"pooler/goutils/httpclient"
	"pooler/goutils/ipfsutils"
	"pooler/goutils/settings"
	contractApi "pooler/goutils/smartcontract/api"
	"pooler/goutils/smartcontract/transactions"
	"pooler/goutils/taskmgr"
	w3storage "pooler/goutils/w3s"
	"pooler/payload-commit/datamodel"
	"pooler/payload-commit/signer"
)

type PayloadCommitService struct {
	settingsObj *settings.SettingsObj
	redisCache  *caching.RedisCache
	ethClient   *ethclient.Client
	contractAPI *contractApi.ContractApi
	ipfsClient  *ipfsutils.IpfsClient
	web3sClient *w3storage.W3S
	diskCache   *caching.LocalDiskCache
	txManager   *transactions.TxManager
	privKey     *ecdsa.PrivateKey
}

// InitPayloadCommitService initializes the payload commit service
func InitPayloadCommitService() *PayloadCommitService {
	settingsObj, err := gi.Invoke[*settings.SettingsObj]()
	if err != nil {
		log.WithError(err).Fatal("failed to invoke settings object")
	}

	redisCache, err := gi.Invoke[*caching.RedisCache]()
	if err != nil {
		log.WithError(err).Fatal("failed to invoke redis cache")
	}

	ethClient, err := gi.Invoke[*ethclient.Client]()
	if err != nil {
		log.WithError(err).Fatal("failed to invoke eth client")
	}

	contractAPI, err := gi.Invoke[*contractApi.ContractApi]()
	if err != nil {
		log.WithError(err).Fatal("failed to invoke contract api")
	}

	ipfsClient, err := gi.Invoke[*ipfsutils.IpfsClient]()
	if err != nil {
		log.WithError(err).Fatal("failed to invoke ipfs client")
	}

	web3sClient, err := gi.Invoke[*w3storage.W3S]()
	if err != nil {
		log.WithError(err).Fatal("failed to invoke web3s client")
	}

	diskCache, err := gi.Invoke[*caching.LocalDiskCache]()
	if err != nil {
		log.WithError(err).Fatal("failed to invoke disk cache")
	}

	privKey, err := signer.GetPrivateKey(settingsObj.Signer.PrivateKey)
	if err != nil {
		log.WithError(err).Fatal("failed to get private key")
	}

	pcService := &PayloadCommitService{
		settingsObj: settingsObj,
		redisCache:  redisCache,
		ethClient:   ethClient,
		contractAPI: contractAPI,
		ipfsClient:  ipfsClient,
		web3sClient: web3sClient,
		diskCache:   diskCache,
		txManager:   transactions.NewNonceManager(),
		privKey:     privKey,
	}

	_ = pcService.initLocalCachedData()

	if err := gi.Inject(pcService); err != nil {
		log.WithError(err).Fatal("failed to inject payload commit service")
	}

	return pcService
}

func (s *PayloadCommitService) Run(msgBody []byte, topic string) error {
	log.WithField("msg", string(msgBody)).Debug("running new task")

	if strings.Contains(topic, taskmgr.FinalizedSuffix) {
		finalizedEventMsg := new(datamodel.PayloadCommitFinalizedMessage)

		err := json.Unmarshal(msgBody, finalizedEventMsg)
		if err != nil {
			log.WithError(err).Error("failed to unmarshal finalized payload commit message")

			return err
		}

		err = s.HandleFinalizedPayloadCommitTask(finalizedEventMsg)
		if err != nil {
			return err
		}
	}

	if strings.Contains(topic, taskmgr.DataSuffix) {
		payloadCommitMsg := new(datamodel.PayloadCommitMessage)

		err := json.Unmarshal(msgBody, payloadCommitMsg)
		if err != nil {
			log.WithError(err).Error("failed to unmarshal payload commit message")

			return err
		}

		err = s.HandlePayloadCommitTask(payloadCommitMsg)
		if err != nil {
			return err
		}
	}

	return nil
}

func (s *PayloadCommitService) HandlePayloadCommitTask(msg *datamodel.PayloadCommitMessage) error {
	log.WithField("project_id", msg.ProjectID).Info("handling payload commit task")

	// check if project exists
	// projects, err := s.contractAPI.GetProjects(&bind.CallOpts{})
	//
	// if err != nil {
	// 	log.WithError(err).Error("failed to get projects from contract")
	// 	return err
	// }
	//
	// projectExists := false
	// for _, project := r ange projects {
	// 	if project == msg.ProjectID {
	// 		projectExists = true
	// 		break
	// 	}
	// }
	//
	// if !projectExists {
	// 	log.WithField("project_id", msg.ProjectID).Error("project does not exist, skipping payload commit")
	//
	// 	return nil
	// }

	// upload payload commit msg to ipfs and web3 storage
	err := s.uploadToIPFSandW3s(msg)
	if err != nil {
		log.WithError(err).Error("failed to upload payload commit message to ipfs")
	}

	go func() {
		_ = s.storePayloadToDiskCache(msg)
		_ = s.redisCache.AddPayloadCID(context.Background(), msg.ProjectID, msg.SnapshotCID, float64(msg.EpochID))
	}()

	signerData, signature, err := s.signPayload()
	if err != nil {
		return err
	}

	s.txManager.Mu.Lock()
	defer func() {
		s.txManager.Nonce++
		s.txManager.Mu.Unlock()
	}()

	txPayload := &datamodel.SnapshotRelayerPayload{
		ProjectID:   msg.ProjectID,
		EpochID:     msg.EpochID,
		SnapshotCID: msg.SnapshotCID,
		Request:     signerData.Message,
		Signature:   string(signature),
	}

	// if relayer service url is not set in config, send payload commit message with signature to contract directly
	if *s.settingsObj.Relayer.Host == "" {
		err = s.txManager.SubmitSnapshot(s.contractAPI, s.privKey, signerData, txPayload, signature)
		if err != nil {
			return err
		}

		return nil
	}

	// send payload commit message with signature to relayer
	err = backoff.Retry(func() error {
		err = s.sendSignatureToRelayer(txPayload)
		if err != nil {
			return err
		}

		return nil
	}, backoff.NewExponentialBackOff())
	if err != nil {
		log.WithError(err).Error("failed to send signature to relayer")
		return err
	}

	return nil
}

// HandleFinalizedPayloadCommitTask handles finalized payload commit task
func (s *PayloadCommitService) HandleFinalizedPayloadCommitTask(msg *datamodel.PayloadCommitFinalizedMessage) error {
	log.Debug("handling finalized payload commit task")

	// check if payload is already in cache
	payloadCid, err := s.redisCache.GetPayloadCidAtEpochID(context.Background(), msg.Message.ProjectID, msg.Message.EpochID)
	if err != nil {
		return err
	}

	if payloadCid != msg.Message.SnapshotCID {
		log.WithField("payload_cid", payloadCid).WithField("msg_cid", msg.Message.SnapshotCID).Error("payload cid does not match")
		err = s.redisCache.RemovePayloadCIDAtEpochID(context.Background(), msg.Message.ProjectID, msg.Message.EpochID)
		if err != nil {
			log.WithError(err).Error("failed to remove payload cid from cache")

			return err
		}

		err = s.redisCache.AddPayloadCID(context.Background(), msg.Message.ProjectID, msg.Message.SnapshotCID, float64(msg.Message.EpochID))
		if err != nil {
			log.WithError(err).Error("failed to add payload cid to cache")

			return err
		}
	}

	return nil
}

func (s *PayloadCommitService) uploadToIPFSandW3s(msg *datamodel.PayloadCommitMessage) error {
	log.WithField("msg", msg).Debug("uploading payload commit msg to ipfs and web3 storage")
	wg := sync.WaitGroup{}

	wg.Add(2)

	// upload to ipfs
	var ipfsUploadErr error
	go func() {
		defer wg.Done()
		ipfsUploadErr = backoff.Retry(func() error {
			ipfsUploadErr = s.ipfsClient.UploadSnapshotToIPFS(msg)
			if ipfsUploadErr != nil {
				log.WithError(ipfsUploadErr).Error("failed to upload snapshot to ipfs, retrying")

				return ipfsUploadErr
			}

			return nil
		}, backoff.NewExponentialBackOff())

		if ipfsUploadErr != nil {
			log.WithError(ipfsUploadErr).Error("failed to upload snapshot to ipfs after max retries")
		}
	}()

	// upload to web3 storage
	var w3sUploadErr error
	var snapshotCid string
	if msg.Web3Storage {
		go func() {
			wg.Done()
			w3sUploadErr = backoff.Retry(func() error {
				snapshotCid, w3sUploadErr = s.uploadToW3s(msg)
				if w3sUploadErr != nil {
					return w3sUploadErr
				}

				return nil
			}, backoff.NewExponentialBackOff())

			if w3sUploadErr != nil {
				log.WithError(w3sUploadErr).Error("failed to upload snapshot to web3 storage after max retries")
			}
		}()
	}

	wg.Wait()

	if ipfsUploadErr != nil && !msg.Web3Storage {
		return fmt.Errorf("failed to upload to ipfs")
	}

	if ipfsUploadErr != nil && w3sUploadErr != nil {
		return fmt.Errorf("failed to upload to ipfs and web3 storage")
	}

	if ipfsUploadErr != nil && w3sUploadErr == nil {
		msg.SnapshotCID = snapshotCid

		return nil
	}

	return nil
}

func (s *PayloadCommitService) uploadToW3s(msg *datamodel.PayloadCommitMessage) (string, error) {
	log.Debug("uploading payload commit message to web3 storage")

	reqURL := s.settingsObj.Web3Storage.URL + s.settingsObj.Web3Storage.UploadURLSuffix

	defaultHTTPClient := httpclient.GetDefaultHTTPClient()

	payloadCommit, err := json.Marshal(msg.Message)
	if err != nil {
		log.WithError(err).Error("failed to marshal payload commit message")

		return "", err
	}

	req, err := retryablehttp.NewRequest(http.MethodPost, reqURL, bytes.NewBuffer(payloadCommit))
	if err != nil {
		log.WithError(err).Error("failed to create request to web3.storage")

		return "", err
	}

	req.Header.Add("Authorization", "Bearer "+s.settingsObj.Web3Storage.APIToken)
	req.Header.Add("accept", "application/json")

	err = s.web3sClient.Limiter.Wait(context.Background())
	if err != nil {
		log.Errorf("web3 storage rate limiter wait errored")

		return "", err
	}

	log.WithField("msg", string(payloadCommit)).Debug("sending request to web3.storage")

	res, err := defaultHTTPClient.Do(req)
	if err != nil {
		log.WithError(err).Error("failed to send request to web3.storage")

		return "", err
	}

	defer res.Body.Close()

	web3resp := new(datamodel2.Web3StoragePutResponse)

	respBody, err := io.ReadAll(res.Body)
	if err != nil {
		log.WithError(err).Error("failed to read response body from web3.storage")

		return "", err
	}

	if res.StatusCode == http.StatusOK {
		err = json.Unmarshal(respBody, web3resp)
		if err != nil {
			log.WithError(err).Error("failed to unmarshal response from web3.storage")

			return "", err
		}

		log.WithField("cid", web3resp.CID).Info("successfully uploaded payload commit message to web3.storage")

		return web3resp.CID, nil
	}

	resp := new(datamodel2.Web3StorageErrResponse)

	err = json.Unmarshal(respBody, resp)
	if err != nil {
		log.WithError(err).Error("failed to unmarshal error response from web3.storage")
	} else {
		log.WithField("payloadCommit", string(payloadCommit)).WithField("error", resp.Message).Error("web3.storage upload error")
	}

	return "", errors.New(resp.Message)
}

// storePayloadToDiskCache stores the payload commit message to disk cache
func (s *PayloadCommitService) storePayloadToDiskCache(msg *datamodel.PayloadCommitMessage) error {
	cachePath := s.settingsObj.PayloadCachePath

	cachePath = fmt.Sprintf("%s%s/%s", cachePath, msg.ProjectID, msg.SnapshotCID)

	byteData, err := json.Marshal(msg)
	if err != nil {
		log.WithError(err).Error("failed to marshal payload commit message")

		return err
	}

	err = s.diskCache.Write(cachePath, byteData)
	if err != nil {
		log.WithError(err).Error("failed to write payload commit message to cache")

		return err
	}

	return nil
}

// signPayload signs the payload commit message for relayer
func (s *PayloadCommitService) signPayload() (*apitypes.TypedData, []byte, error) {
	log.Debug("signing payload commit message")

	signerData, err := signer.GetSignerData(s.ethClient)
	if err != nil {
		log.WithError(err).Error("failed to get signer data")

		return nil, nil, err
	}

	signature, err := signer.SignMessage(s.privKey, signerData)
	if err != nil {
		log.WithError(err).Error("failed to sign message")

		return nil, nil, err
	}

	verified := signer.VerifySignature(signature, signerData)
	if !verified {
		log.Error("failed to verify signature")

		return nil, nil, errors.New("failed to verify signature")
	}

	return signerData, signature, nil
}

// sendSignatureToRelayer sends the signature to the relayer
func (s *PayloadCommitService) sendSignatureToRelayer(payload *datamodel.SnapshotRelayerPayload) error {
	log.Debug("sending signature to relayer")
	httpClient := httpclient.GetDefaultHTTPClient()

	url := *s.settingsObj.Relayer.Host + *s.settingsObj.Relayer.Endpoint

	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		log.WithError(err).Error("failed to marshal payload")

		return err
	}

	req, err := retryablehttp.NewRequest(http.MethodPost, url, bytes.NewBuffer(payloadBytes))
	if err != nil {
		log.WithError(err).Error("failed to create request to relayer")

		return err
	}

	req.Header.Add("Content-Type", "application/json")

	res, err := httpClient.Do(req)
	if err != nil {
		log.WithError(err).Error("failed to send request to relayer")

		return err
	}

	defer res.Body.Close()

	if res.StatusCode != http.StatusOK {
		log.WithField("status", res.StatusCode).Error("failed to send request to relayer")

		return errors.New("failed to send request to relayer, status not ok")
	}

	log.Info("successfully sent signature to relayer")

	return nil
}

// initLocalCachedData fills data in redis cache from smart contract if not present locally
func (s *PayloadCommitService) initLocalCachedData() error {
	log.Debug("initializing local cached data")

	projects, err := s.redisCache.GetStoredProjects(context.Background())
	if err != nil {
		log.WithError(err).Error("failed to get stored projects from redis cache")

		return err
	}

	if len(projects) > 0 {
		return nil
	}

	// get projects from smart contract
	projects, err = s.contractAPI.GetProjects(&bind.CallOpts{})
	if err != nil {
		log.WithError(err).Error("failed to get projects from smart contract")

		return err
	}

	if len(projects) == 0 {
		return nil
	}

	// store projects in redis cache
	err = s.redisCache.StoreProjects(context.Background(), projects)
	if err != nil {
		log.WithError(err).Error("failed to store projects in redis cache")

		return err
	}

	return nil
}
