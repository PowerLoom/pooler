package httpclient

import (
	"net/http"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	log "github.com/sirupsen/logrus"
	"github.com/swagftw/gi"

	"pooler/goutils/settings"
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
	retryClient.HTTPClient.Timeout = time.Duration(settingsObj.IpfsConfig.Timeout) * time.Second

	return retryClient
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
