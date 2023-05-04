package slackutils

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"time"

	log "github.com/sirupsen/logrus"
	"golang.org/x/time/rate"
)

type SlackNotifyReq struct {
	Data          string `json:"errorDetails"`
	IssueSeverity string `json:"severity"`
	Service       string `json:"Service"`
}

type SlackResp struct {
	Error            string `json:"error"`
	Ok               bool   `json:"ok"`
	ResponseMetadata struct {
		Messages []string `json:"messages"`
	} `json:"response_metadata"`
}

var SlackClient *http.Client
var slackNotifyURL string
var rateLimit *rate.Limiter

func InitSlackWorkFlowClient(url string) {
	slackNotifyURL = url
	SlackClient = &http.Client{
		Timeout: 10 * time.Second,
	}

	rateLimit = rate.NewLimiter(1, 1)
}

func NotifySlackWorkflow(reportData string, severity string, service string) error {
	_ = rateLimit.Wait(context.Background())

	reqURL := slackNotifyURL

	if reqURL == "" {
		return nil
	}

	var slackReq SlackNotifyReq

	slackReq.Data = reportData
	slackReq.IssueSeverity = severity
	slackReq.Service = service
	body, err := json.Marshal(slackReq)

	if err != nil {
		log.Fatalf("Failed to marshal request %+v towards Slack Webhook with error %+v", slackReq, err)
		return err
	}
	for retryCount := 0; ; retryCount++ {
		if retryCount == 3 {
			log.Errorf("Giving up notifying slack after retrying for %d times", retryCount)
			return errors.New("failed to notify after maximum retries")
		}
		req, err := http.NewRequest(http.MethodPost, reqURL, bytes.NewBuffer(body))
		if err != nil {
			log.Fatalf("Failed to create new HTTP Req with URL %s for message %+v with error %+v",
				reqURL, slackReq, err)
			return err
		}
		req.Header.Add("Content-Type", "application/json")
		req.Header.Add("accept", "application/json")
		log.Debugf("Sending Req with params to Slack Webhook URL %s.", reqURL)
		res, err := SlackClient.Do(req)
		if err != nil {
			log.WithField("req", slackReq).Errorf("Failed to send request %+v towards Slack Webhook URL %s with error %+v",
				req, reqURL, err)
			time.Sleep(5 * time.Second)
			continue
		}
		defer res.Body.Close()
		var resp SlackResp
		respBody, err := io.ReadAll(res.Body)
		if err != nil {
			log.Errorf("Failed to read response body from Slack Webhook with error %+v",
				err)
			time.Sleep(5 * time.Second)
			continue
		}
		if res.StatusCode == http.StatusOK {
			log.Debugf("Received success response from Slack Webhook with statusCode %d", res.StatusCode)
			return nil
		} else {
			err = json.Unmarshal(respBody, &resp)
			if err != nil {
				log.Errorf("Failed to unmarshal response %+v towards Slack Webhook with error %+v",
					respBody, err)
				time.Sleep(5 * time.Second)
				continue
			}
			log.Errorf("Received Error response %+v from Slack Webhook with statusCode %d and status : %s ",
				resp, res.StatusCode, res.Status)
			time.Sleep(5 * time.Second)
			continue
		}
	}
}
