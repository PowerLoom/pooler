package taskmgr

import (
	"context"
	"errors"

	"github.com/streadway/amqp"

	"audit-protocol/goutils/taskmgr/worker"
)

const (
	TaskSuffix      string = "task"
	DataSuffix      string = ".Data"
	FinalizedSuffix string = ".Finalized"
	DLXSuffix       string = "dlx"
)

// TaskMgr interface is used to publish and consume tasks.
// can be implemented by rabbitmq, kafka, webhooks etc.
type TaskMgr interface {
	Publish(ctx context.Context) error

	// Consume creates a new consumer and starts consuming tasks.
	// as this method can be implemented by different task managers, we need to pass config for consumer initialization.
	// for example, in rabbitmq, we need to create a new channel and declare a queue.
	// in http webhook, we need to create a new http server listening on a port and configured path, etc.
	// we need workerType to identify which worker is consuming the tasks and depending on the worker type,
	// we can create configure for consumer initialization.
	Consume(ctx context.Context, workerType worker.Type, msgChan chan TaskHandler, errChan chan error) error

	Shutdown(ctx context.Context) error
}

type TaskHandler interface {
	GetBody() []byte
	GetTopic() string
	Ack() error
	Nack(requeue bool) error
}

type Task struct {
	Msg   interface{} // this is original message type from broker, e.g. amqp.Delivery, kafka.Message, simple http request body, etc.
	Topic string
}

var _ TaskHandler = (*Task)(nil)

func (t *Task) GetTopic() string {
	return t.Topic
}

func (t *Task) GetBody() []byte {
	switch msg := t.Msg.(type) {
	case amqp.Delivery:
		return msg.Body
	default:
		return nil
	}
}

func (t *Task) Ack() error {
	switch msg := t.Msg.(type) {
	case amqp.Delivery:
		return msg.Ack(false)
	default:
		return nil
	}
}

func (t *Task) Nack(requeue bool) error {
	switch msg := t.Msg.(type) {
	case amqp.Delivery:
		return msg.Nack(false, requeue)
	default:
		return nil
	}
}

type ErrTaskMgr error

var (
	ErrConsumerInitFailed = errors.New("failed to initialize consumer")
)
