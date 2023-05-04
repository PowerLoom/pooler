package worker

import (
	"context"

	"github.com/cenkalti/backoff/v4"
	"github.com/remeh/sizedwaitgroup"
	log "github.com/sirupsen/logrus"
	"github.com/swagftw/gi"

	"audit-protocol/goutils/settings"
	"audit-protocol/goutils/taskmgr"
	rabbitmqMgr "audit-protocol/goutils/taskmgr/rabbitmq"
	worker2 "audit-protocol/goutils/taskmgr/worker"
	"audit-protocol/payload-commit/service"
)

type Worker struct {
	service  *service.PayloadCommitService
	taskmgr  taskmgr.TaskMgr
	settings *settings.SettingsObj
}

func (w *Worker) ConsumeTask() error {
	// create buffered channel to limit the number of concurrent tasks.
	// buffered channel can is used to accept multiple messages and then process them in parallel.
	// as messages are generated at lower pace than they are consumed, we can use unbuffered channel as well.
	// TBD: we can use unbuffered channel as well.
	taskChan := make(chan taskmgr.TaskHandler, 5)
	defer close(taskChan)

	// start consuming messages in separate go routine.
	// messages will be sent back over taskChan.
	go func() {
		err := backoff.Retry(
			func() error {
				errChan := make(chan error)
				err := w.taskmgr.Consume(context.Background(), worker2.TypePayloadCommitWorker, taskChan, errChan)
				if err != nil {
					log.WithError(err).Error("failed to consume the message")
				}

				err = <-errChan
				if err != nil {
					log.WithError(err).Error("failed to consume the message")

					return err
				}

				return nil
			}, backoff.NewExponentialBackOff())

		if err != nil {
			log.WithError(err).Error("failed to consume the message")
		}
	}()

	// create a wait group to wait for previous the tasks to finish.
	// limit number of concurrent tasks per Worker
	swg := sizedwaitgroup.New(5)

	for {
		swg.Add()

		// as task chan is buffered channel, we can use it as a semaphore to limit the number of concurrent tasks.
		taskHandler := <-taskChan

		go func(taskHandler taskmgr.TaskHandler) {
			msgBody := taskHandler.GetBody()

			log.WithField("msg", string(msgBody)).Debug("received message")

			err := w.service.Run(msgBody, taskHandler.GetTopic())
			if err != nil {
				log.WithError(err).Error("failed to run the task")

				err = backoff.Retry(func() error {
					return taskHandler.Nack(false)
				}, backoff.WithMaxRetries(backoff.NewExponentialBackOff(), uint64(*w.settings.RetryCount)))
				if err != nil {
					log.WithError(err).Errorf("failed to nack the message")
				}
			} else {
				err = backoff.Retry(func() error {
					return taskHandler.Ack()
				}, backoff.WithMaxRetries(backoff.NewExponentialBackOff(), uint64(*w.settings.RetryCount)))
				if err != nil {
					log.WithError(err).Error("failed to ack the message")
				}
			}

			swg.Done()
		}(taskHandler)

		// wait till all the previous tasks are finished.
		swg.Wait()
	}
}

// should be implemented by all the workers
var _ worker2.Worker = (*Worker)(nil)

// NewWorker creates a new *Worker listening for pruning tasks published by service responsible for creating segments
// a single Worker has capability to run multiple tasks concurrently using go routines.
// running multiple instances of this whole service will create multiple workers which can horizontally scale the service.
func NewWorker() *Worker {
	pcService, err := gi.Invoke[*service.PayloadCommitService]()
	if err != nil {
		log.WithError(err).Fatal("failed to invoke payload commit service")
	}

	settingsObj, err := gi.Invoke[*settings.SettingsObj]()
	if err != nil {
		log.WithError(err).Fatal("failed to invoke settings")
	}

	mgr, err := gi.Invoke[*rabbitmqMgr.RabbitmqTaskMgr]()
	if err != nil {
		log.WithError(err).Fatal("failed to invoke rabbitmq task manager")
	}

	return &Worker{service: pcService, settings: settingsObj, taskmgr: mgr}
}

func (w *Worker) ShutdownWorker() {
	err := w.taskmgr.Shutdown(context.Background())
	if err != nil {
		log.WithError(err).Error("failed to shutdown the worker")
	}
}
