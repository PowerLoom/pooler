package taskmgr

import (
	"context"
	"errors"
	"fmt"
	"net"
	"strconv"
	"strings"

	"github.com/swagftw/gi"

	"audit-protocol/goutils/settings"
	"audit-protocol/goutils/taskmgr"
	"audit-protocol/goutils/taskmgr/worker"

	log "github.com/sirupsen/logrus"
	"github.com/streadway/amqp"
)

type RabbitmqTaskMgr struct {
	conn     *amqp.Connection
	settings *settings.SettingsObj
}

var _ taskmgr.TaskMgr = &RabbitmqTaskMgr{}

func NewRabbitmqTaskMgr() *RabbitmqTaskMgr {
	settingsObj, err := gi.Invoke[*settings.SettingsObj]()
	if err != nil {
		log.WithError(err).Fatalf("failed to invoke settingsObj object")
	}

	taskMgr := &RabbitmqTaskMgr{
		conn:     Dial(settingsObj),
		settings: settingsObj,
	}

	if err := gi.Inject(taskMgr); err != nil {
		log.WithError(err).Fatalf("failed to inject dependencies")
	}

	log.Debug("rabbitmq task manager initialized")

	return taskMgr
}

func (r *RabbitmqTaskMgr) Publish(ctx context.Context) error {
	// TODO implement me
	panic("implement me")
}

// getChannel returns a channel from the connection
// this method is also used to create a new channel if channel is closed
func (r *RabbitmqTaskMgr) getChannel(workerType worker.Type) (*amqp.Channel, error) {
	channel, err := r.conn.Channel()
	if err != nil {
		log.Errorf("failed to open a channel on rabbitmq: %v", err)

		return nil, taskmgr.ErrConsumerInitFailed
	}

	exchange := r.getExchange(workerType)

	err = channel.ExchangeDeclare(exchange, "topic", true, false, false, false, nil)
	if err != nil {
		log.Errorf("failed to declare an exchange on rabbitmq: %v", err)

		return nil, taskmgr.ErrConsumerInitFailed
	}

	// dead letter exchange
	dlxExchange := r.settings.Rabbitmq.Setup.Core.DLX

	err = channel.ExchangeDeclare(dlxExchange, "direct", true, false, false, false, nil)
	if err != nil {
		log.Errorf("failed to declare an exchange on rabbitmq: %v", err)

		return nil, taskmgr.ErrConsumerInitFailed
	}

	// declare the queue
	routingKeys := r.getRoutingKeys(workerType) // dag-pruning:task
	dlxRoutingKey := ""
	for _, routingKey := range routingKeys {
		if strings.Contains(routingKey, ":dlx") {
			dlxRoutingKey = routingKey
		}
	}

	if dlxRoutingKey == "" {
		log.Errorf("failed to get dlx routing key")

		return nil, taskmgr.ErrConsumerInitFailed
	}

	queue, err := channel.QueueDeclare(r.getQueue(workerType, ""), false, false, false, false, nil)

	if err != nil {
		log.Errorf("failed to declare a queue on rabbitmq: %v", err)

		return nil, taskmgr.ErrConsumerInitFailed
	}

	// bind the queue to the exchange
	for _, routingKey := range routingKeys {
		// TODO: for now skipping dead letter config
		if strings.Contains(routingKey, ":dlx") {
			continue
		}

		err = channel.QueueBind(queue.Name, routingKey, exchange, false, nil)
		if err != nil {
			log.WithField("routingKey", routingKey).Errorf("failed to bind a queue on rabbitmq: %v", err)

			return nil, taskmgr.ErrConsumerInitFailed
		}
	}

	// err = channel.QueueBind(queue.Name, dlxRoutingKey, dlxExchange, false, nil)
	// if err != nil {
	// 	log.Errorf("failed to bind a queue on rabbitmq: %v", err)
	//
	// 	return nil, taskmgr.ErrConsumerInitFailed
	// }

	return channel, nil
}

// Consume consumes messages from the queue
func (r *RabbitmqTaskMgr) Consume(ctx context.Context, workerType worker.Type, msgChan chan taskmgr.TaskHandler, errChan chan error) error {
	channel, err := r.getChannel(workerType)
	if err != nil {
		return err
	}

	defer func(channel *amqp.Channel) {
		err = channel.Close()
		if err != nil && !errors.Is(err, amqp.ErrClosed) {
			log.Errorf("failed to close channel on rabbitmq: %v", err)
		}
	}(channel)

	defer func() {
		err = r.conn.Close()
		if err != nil && !errors.Is(err, amqp.ErrClosed) {
			log.Errorf("failed to close connection on rabbitmq: %v", err)
		}
	}()

	queueName := r.getQueue(workerType, taskmgr.TaskSuffix)
	// consume messages
	msgs, err := channel.Consume(
		queueName,
		"",
		false,
		false,
		false,
		false,
		nil,
	)
	if err != nil {
		log.Errorf("failed to register a consumer on rabbitmq: %v", err)

		return err
	}

	log.Infof("RabbitmqTaskMgr: consuming messages from queue %s", queueName)

	forever := make(chan *amqp.Error)

	forever = channel.NotifyClose(forever)

	go func() {
		for msg := range msgs {
			log.Debug(msg.Headers)

			log.Infof("received new message")

			task := &taskmgr.Task{Msg: msg, Topic: msg.RoutingKey}

			msgChan <- task
		}
	}()

	err = <-forever
	if err != nil {
		log.WithError(err).WithField("queueName", queueName).Error("connection closed while consuming messages")
	}

	// send back error due to rabbitmq channel closed
	errChan <- err

	return nil
}

func Dial(config *settings.SettingsObj) *amqp.Connection {
	rabbitmqConfig := config.Rabbitmq

	url := fmt.Sprintf("amqp://%s:%s@%s/", rabbitmqConfig.User, rabbitmqConfig.Password, net.JoinHostPort(rabbitmqConfig.Host, strconv.Itoa(rabbitmqConfig.Port)))

	conn, err := amqp.Dial(url)
	if err != nil {
		log.Panicf("failed to connect to RabbitMQ: %v", err)
	}

	return conn
}

func (r *RabbitmqTaskMgr) getExchange(workerType worker.Type) string {
	switch workerType {
	case worker.TypePruningServiceWorker:
		return r.settings.Rabbitmq.Setup.Core.Exchange
	case worker.TypePayloadCommitWorker:
		return fmt.Sprintf("%s%s", r.settings.Rabbitmq.Setup.Core.CommitPayloadExchange, r.settings.PoolerNamespace)
	default:
		return ""
	}
}

func (r *RabbitmqTaskMgr) getQueue(workerType worker.Type, suffix string) string {
	switch workerType {
	case worker.TypePruningServiceWorker:
		return r.settings.Rabbitmq.Setup.Queues.DagPruning.QueueNamePrefix + suffix
	case worker.TypePayloadCommitWorker:
		return fmt.Sprintf("%s%s:%s", r.settings.Rabbitmq.Setup.Queues.CommitPayloads.QueueNamePrefix, r.settings.PoolerNamespace, r.settings.InstanceId)
	default:
		return ""
	}
}

// getRoutingKeys returns the routing key(s) for the given worker type
func (r *RabbitmqTaskMgr) getRoutingKeys(workerType worker.Type) []string {
	switch workerType {
	case worker.TypePruningServiceWorker:
		return []string{
			r.settings.Rabbitmq.Setup.Queues.DagPruning.RoutingKeyPrefix + taskmgr.TaskSuffix,
			r.settings.Rabbitmq.Setup.Queues.DagPruning.RoutingKeyPrefix + taskmgr.DLXSuffix,
		}
	case worker.TypePayloadCommitWorker:
		return []string{
			fmt.Sprintf("%s%s:%s%s", r.settings.Rabbitmq.Setup.Queues.CommitPayloads.RoutingKeyPrefix, r.settings.PoolerNamespace, r.settings.InstanceId, taskmgr.FinalizedSuffix),
			fmt.Sprintf("%s%s:%s%s", r.settings.Rabbitmq.Setup.Queues.CommitPayloads.RoutingKeyPrefix, r.settings.PoolerNamespace, r.settings.InstanceId, taskmgr.DataSuffix),
			r.settings.Rabbitmq.Setup.Queues.CommitPayloads.RoutingKeyPrefix + taskmgr.DLXSuffix,
		}
	default:
		return nil
	}
}

func (r *RabbitmqTaskMgr) Shutdown(ctx context.Context) error {
	if err := r.conn.Close(); err != nil && !errors.Is(err, amqp.ErrClosed) {
		log.Errorf("failed to close connection on rabbitmq: %v", err)

		return err
	}

	return nil
}
