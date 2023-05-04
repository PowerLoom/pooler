package w3storage

import (
    log "github.com/sirupsen/logrus"
    "github.com/swagftw/gi"
    "github.com/web3-storage/go-w3s-client"
    "golang.org/x/time/rate"

    "audit-protocol/goutils/settings"
)

type W3S struct {
    Client  w3s.Client
    Limiter *rate.Limiter
}

func InitW3S() {
    settingsObj, err := gi.Invoke[*settings.SettingsObj]()
    if err != nil {
        log.WithError(err).Fatal("error getting settings object")
    }

    client, err := w3s.NewClient(w3s.WithToken(settingsObj.Web3Storage.APIToken))
    if err != nil {
        log.WithError(err).Fatal("error creating w3s client")
    }

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

    rateLimiter := rate.NewLimiter(tps, burst)

    w := &W3S{
        Client:  client,
        Limiter: rateLimiter,
    }

    err = gi.Inject(w)
    if err != nil {
        log.WithError(err).Fatal("error injecting w3s")
    }
}
