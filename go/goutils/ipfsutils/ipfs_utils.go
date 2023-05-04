package ipfsutils

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"strings"
	"time"

	"github.com/cenkalti/backoff/v4"
	shell "github.com/ipfs/go-ipfs-api"
	ma "github.com/multiformats/go-multiaddr"
	log "github.com/sirupsen/logrus"
	"github.com/swagftw/gi"
	"golang.org/x/time/rate"

	"audit-protocol/goutils/datamodel"
	"audit-protocol/goutils/httpclient"
	"audit-protocol/goutils/settings"
	datamodel2 "audit-protocol/payload-commit/datamodel"
)

type IpfsClient struct {
	ipfsClient            *shell.Shell
	ipfsClientRateLimiter *rate.Limiter
}

// InitClient initializes the IPFS client.
// Init functions should not be treated as methods, they are just functions that return a pointer to the struct.
func InitClient(url string, poolSize int, rateLimiter *settings.RateLimiter, timeoutSecs int) *IpfsClient {
	// no need to use underscore for _url, it is just a local variable
	// _url := url
	url = ParseMultiAddrURL(url)

	ipfsHTTPClient := httpclient.GetIPFSHTTPClient()

	log.Debug("Initializing the IPFS client with IPFS Daemon URL:", url)

	client := new(IpfsClient)
	client.ipfsClient = shell.NewShellWithClient(url, ipfsHTTPClient.HTTPClient)
	timeout := time.Duration(timeoutSecs * int(time.Second))
	client.ipfsClient.SetTimeout(timeout)

	log.Debugf("Setting IPFS timeout of %f seconds", timeout.Seconds())

	tps := rate.Limit(10) // 10 TPS
	burst := 10

	if rateLimiter != nil {
		burst = rateLimiter.Burst

		if rateLimiter.RequestsPerSec == -1 {
			tps = rate.Inf
			burst = 0
		} else {
			tps = rate.Limit(rateLimiter.RequestsPerSec)
		}
	}

	log.Infof("Rate Limit configured for IPFS Client at %v TPS with a burst of %d", tps, burst)
	client.ipfsClientRateLimiter = rate.NewLimiter(tps, burst)

	// exit if injection fails
	if err := gi.Inject(client); err != nil {
		log.Fatalln("Failed to inject dependencies", err)
	}

	return client
}

func ParseMultiAddrURL(url string) string {
	if _, err := ma.NewMultiaddr(url); err == nil {
		url = strings.Split(url, "/")[2] + ":" + strings.Split(url, "/")[4]
	}

	return url
}

func (client *IpfsClient) GetDagBlock(dagCid string) (*datamodel.DagBlock, error) {
	dagBlock := new(datamodel.DagBlock)
	l := log.WithField("dagCid", dagCid)

	err := client.ipfsClientRateLimiter.Wait(context.Background())
	if err != nil {
		log.Errorf("IPFSClient Rate Limiter wait timeout with error %+v", err)

		return nil, err
	}

	err = backoff.Retry(func() error {
		err = client.ipfsClient.DagGet(dagCid, dagBlock)
		if err != nil {
			return err
		}

		return nil
	}, backoff.WithMaxRetries(backoff.NewExponentialBackOff(), 5))
	if err != nil {
		l.WithError(err).Error("failed to get block from IPFS")

		return nil, err
	}

	return dagBlock, nil
}

// GetPayloadChainHeightRang fetches the payload chain height range for given CID from IPFS
func (client *IpfsClient) GetPayloadChainHeightRang(payloadCid string) (*datamodel.ChainHeightRange, error) {
	payload := new(datamodel.DagPayload)

	err := client.ipfsClientRateLimiter.Wait(context.Background())
	if err != nil {
		log.Errorf("IPFSClient Rate Limiter wait timeout with error %+v", err)

		return nil, err
	}

	var data io.ReadCloser

	err = backoff.Retry(func() error {
		data, err = client.ipfsClient.Cat(payloadCid)
		if err != nil {
			return err
		}

		return nil
	}, backoff.WithMaxRetries(backoff.NewExponentialBackOff(), 5))
	if err != nil {
		log.Error("Failed to fetch Payload from IPFS, CID:", payloadCid, ", error:", err)

		return nil, err
	}

	buf := new(bytes.Buffer)

	_, err = buf.ReadFrom(data)
	if err != nil {
		log.Error("Failed to read Payload from IPFS, CID:", payloadCid, ", error:", err)

		return nil, err
	}

	err = json.Unmarshal(buf.Bytes(), payload)
	if err != nil {
		log.Error("Failed to Unmarshal Json Payload from IPFS, CID:", payloadCid, ", bytes:", buf, ", error:", err)

		return nil, err
	}

	log.Infof("Fetched Payload with CID %s from IPFS: %+v", payloadCid, payload)

	return payload.ChainHeightRange, nil
}

func (client *IpfsClient) UploadSnapshotToIPFS(payloadCommit *datamodel2.PayloadCommitMessage) error {
	err := client.ipfsClientRateLimiter.Wait(context.Background())
	if err != nil {
		log.WithError(err).Error("ipfs rate limiter errored")

		return err
	}

	msg, err := json.Marshal(payloadCommit.Message)
	if err != nil {
		log.WithError(err).Error("failed to marshal payload commit message")

		return err
	}

	snapshotCid, err := client.ipfsClient.Add(bytes.NewReader(msg), shell.CidVersion(1))
	if err != nil {
		log.WithError(err).Error("failed to add snapshot to ipfs")

		return err
	}

	log.WithField("snapshotCID", snapshotCid).
		WithField("epochId", payloadCommit.EpochID).
		Debug("ipfs add Successful")

	payloadCommit.SnapshotCID = snapshotCid

	return nil
}

func (client *IpfsClient) GetPayloadFromIPFS(payloadCid string) (*datamodel.DagPayload, error) {
	client.ipfsClientRateLimiter.Wait(context.Background())

	payload := new(datamodel.DagPayload)
	l := log.WithField("payloadCid", payloadCid)

	l.Debugf("fetching payloadCid %s from IPFS", payloadCid)

	var data io.ReadCloser
	var err error

	err = backoff.Retry(func() error {
		data, err = client.ipfsClient.Cat(payloadCid)
		if err != nil {
			return err
		}

		return nil
	}, backoff.WithMaxRetries(backoff.NewExponentialBackOff(), 5))
	if err != nil {
		log.WithError(err).WithField("payloadCID", payloadCid).Error("Failed to fetch Payload from IPFS")

		return nil, err
	}

	buf := new(bytes.Buffer)

	_, err = buf.ReadFrom(data)
	if err != nil {
		l.WithError(err).Errorf("failed to read payload")

		return payload, err
	}

	err = json.Unmarshal(buf.Bytes(), payload)
	if err != nil {
		l.WithError(err).WithField("payload", payload).
			Errorf("failed to unmarshal json payload from IPFS")

		return nil, err
	}

	l.Debugf("fetched payload from ipfs")

	return payload, nil
}

func (client *IpfsClient) UnPinCidsFromIPFS(projectID string, cids map[int]string) error {
	for height, cid := range cids {
		err := client.ipfsClientRateLimiter.Wait(context.Background())
		if err != nil {
			log.Warnf("IPFSClient Rate Limiter wait timeout with error %+v", err)

			continue
		}

		log.Debugf("Unpinning CID %s at height %d from IPFS for project %s", cid, height, projectID)

		err = backoff.Retry(func() error {
			err = client.ipfsClient.Unpin(cid)
			if err != nil {
				// CID has already been unpinned.
				if err.Error() == "pin/rm: not pinned or pinned indirectly" || err.Error() == "pin/rm: pin is not part of the pinset" {
					log.Debugf("CID %s for project %s at height %d could not be unpinned from IPFS as it was not pinned on the IPFS node.", cid, projectID, height)

					return nil
				}

				log.Warnf("Failed to unpin CID %s from ipfs for project %s at height %d due to error %+v", cid, projectID, height, err)

				return err
			}

			log.Debugf("Unpinned CID %s at height %d from IPFS successfully for project %s", cid, height, projectID)

			return nil
		}, backoff.WithMaxRetries(backoff.NewExponentialBackOff(), 3))
	}

	return nil
}

// testing and simulation methods

// AddFileToIPFS adds a file to IPFS and returns the CID of the file
func (client *IpfsClient) AddFileToIPFS(data []byte) (string, error) {
	err := client.ipfsClientRateLimiter.Wait(context.Background())
	if err != nil {
		return "", err
	}

	cid, err := client.ipfsClient.Add(bytes.NewReader(data), shell.CidVersion(1))
	if err != nil {
		return "", err
	}

	return cid, nil
}
