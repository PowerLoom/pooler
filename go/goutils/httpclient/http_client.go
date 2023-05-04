package httpclient

import (
	"net/http"
	"time"

	log "github.com/sirupsen/logrus"
	"github.com/swagftw/gi"
	"golang.org/x/time/rate"

	"github.com/hashicorp/go-retryablehttp"

	"audit-protocol/goutils/settings"
)

func GetIPFSHTTPClient() *retryablehttp.Client {
	settingsObj, err := gi.Invoke[*settings.SettingsObj]()
	if err != nil {
		log.Fatalf("Error getting settings object: %v", err)
	}
	transport := http.Transport{
		MaxIdleConns:        settingsObj.Web3Storage.MaxIdleConns,
		MaxConnsPerHost:     settingsObj.Web3Storage.MaxIdleConns,
		MaxIdleConnsPerHost: settingsObj.Web3Storage.MaxIdleConns,
		IdleConnTimeout:     time.Duration(settingsObj.Web3Storage.IdleConnTimeout),
		DisableCompression:  true,
	}

	retryClient := retryablehttp.NewClient()
	retryClient.RetryMax = *settingsObj.RetryCount
	retryClient.Backoff = retryablehttp.DefaultBackoff

	retryClient.HTTPClient.Transport = &transport
	retryClient.HTTPClient.Timeout = time.Duration(settingsObj.PruningServiceSettings.IpfsTimeout) * time.Second

	return retryClient
}

func GetW3sHTTPClient(settingsObj *settings.SettingsObj) (*retryablehttp.Client, *rate.Limiter) {
	t := http.Transport{
		// TLSClientConfig:    &tls.Config{KeyLogWriter: kl, InsecureSkipVerify: true},
		MaxIdleConns:        settingsObj.Web3Storage.MaxIdleConns,
		MaxConnsPerHost:     settingsObj.Web3Storage.MaxIdleConns,
		MaxIdleConnsPerHost: settingsObj.Web3Storage.MaxIdleConns,
		IdleConnTimeout:     time.Duration(settingsObj.Web3Storage.IdleConnTimeout),
		DisableCompression:  true,
	}

	retryClient := retryablehttp.NewClient()
	retryClient.RetryMax = *settingsObj.RetryCount
	retryClient.Backoff = retryablehttp.DefaultBackoff

	retryClient.HTTPClient.Transport = &t
	retryClient.HTTPClient.Timeout = time.Duration(settingsObj.PruningServiceSettings.IpfsTimeout) * time.Second

	// Default values
	tps := rate.Limit(1) // 3 TPS
	burst := 1
	if settingsObj.PruningServiceSettings.Web3Storage.RateLimit != nil {
		burst = settingsObj.PruningServiceSettings.Web3Storage.RateLimit.Burst
		if settingsObj.PruningServiceSettings.Web3Storage.RateLimit.RequestsPerSec == -1 {
			tps = rate.Inf
			burst = 0
		} else {
			tps = rate.Limit(settingsObj.PruningServiceSettings.Web3Storage.RateLimit.RequestsPerSec)
		}
	}
	log.Infof("Rate Limit configured for web3.storage at %v TPS with a burst of %d", tps, burst)
	web3StorageClientRateLimiter := rate.NewLimiter(tps, burst)

	return retryClient, web3StorageClientRateLimiter
}

// GetDefaultHTTPClient returns a retryablehttp.Client with default values
// use this method for default http client needs for specific settings create custom method
func GetDefaultHTTPClient() *retryablehttp.Client {
	transport := &http.Transport{
		MaxIdleConns:        2,
		MaxConnsPerHost:     2,
		MaxIdleConnsPerHost: 2,
		IdleConnTimeout:     0,
		DisableCompression:  true,
	}

	rawHTTPClient := &http.Client{
		Timeout:   10 * time.Second,
		Transport: transport,
	}

	retryableHTTPClient := retryablehttp.NewClient()
	retryableHTTPClient.RetryMax = 3
	retryableHTTPClient.HTTPClient = rawHTTPClient

	return retryableHTTPClient
}
