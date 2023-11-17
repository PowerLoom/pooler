# -*- coding: utf-8 -*-
# pylint: disable=C0111,C0103,R0205
import functools
import queue
import uuid
from functools import wraps
from typing import Any
from typing import Union

import pika.channel
import pika.exceptions
from tenacity import RetryCallState
from tenacity import Retrying
from tenacity import wait_random_exponential

from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import logger

# setup logging
logger = logger.bind(module='Powerloom|RabbitmqHelpers')


def log_retry_callback(retry_state: RetryCallState) -> bool:
    """
    Logs the attempt number of the retry state and returns True if the exception is an AMQPError and the attempt number is less than 5.

    Args:
        retry_state (RetryCallState): The retry state object.

    Returns:
        bool: True if the exception is an AMQPError and the attempt number is less than 5, False otherwise.
    """
    print(
        'In rabbitmq reconnection helper decorator. attempt number: ',
        retry_state.attempt_number,
    )
    return (
        isinstance(retry_state.outcome.exception(), pika.exceptions.AMQPError) and
        retry_state.attempt_number < 5
    )


def resume_on_rabbitmq_fail(fn) -> Any:
    """
    Decorator function that retries the wrapped function in case of RabbitMQ failure.

    Args:
        fn: The function to be wrapped.

    Returns:
        The wrapped function.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        ret = None
        for attempt in Retrying(
            reraise=True,
            wait=wait_random_exponential(multiplier=1, max=60),
            retry=log_retry_callback,
        ):
            with attempt:
                ret = fn(*args, **kwargs)
        return ret

    return wrapper


# Adapted from:
# https://github.com/pika/pika/blob/12dcdf15d0932c388790e0fa990810bfd21b1a32/examples/asynchronous_publisher_example.py
# https://github.com/pika/pika/blob/12dcdf15d0932c388790e0fa990810bfd21b1a32/examples/asynchronous_consumer_example.py
class RabbitmqSelectLoopInteractor(object):
    """This is an example publisher/consumer that will handle unexpected interactions
    with RabbitMQ such as channel and connection closures.

    If RabbitMQ closes the connection, it will reopen it. You should
    look at the output, as there are limited reasons why the connection may
    be closed, which usually are tied to permission related issues or
    socket timeouts.

    It uses delivery confirmations and illustrates one way to keep track of
    messages that have been sent and if they've been confirmed by RabbitMQ.

    """

    # interval at which the select loop polls to push out new notifications
    PUBLISH_INTERVAL = 0.1

    def __init__(
        self,
        consume_queue_name=None,
        consume_callback=None,
        consumer_worker_name='',
    ):
        """Setup the example publisher object, passing in the URL we will use
        to connect to RabbitMQ.
        """
        self._connection = None
        self._channel: Union[None, pika.channel.Channel] = None
        self.should_reconnect = False
        self._consumer_worker_name = consumer_worker_name
        self.was_consuming = False
        self._consumer_tag = None
        self.queued_messages: dict = dict()
        self._acked = None
        self._nacked = None
        self._message_number = None
        self._closing = False
        self._stopping = False
        self._exchange = None
        self._routing_key = None
        self._consuming = False
        self._consume_queue = consume_queue_name
        self._consume_callback = consume_callback
        # In production, experiment with higher prefetch values
        # for higher consumer throughput
        self._prefetch_count = 1

    def connect(self):
        """This method connects to RabbitMQ, returning the connection handle.
        When the connection is established, the on_connection_open method
        will be invoked by pika.

        :rtype: pika.SelectConnection

        """
        logger.info(
            (
                '{}: RabbitMQ select loop interactor: Creating RabbitMQ select'
                ' ioloop connection to {}'
            ),
            self._consumer_worker_name,
            (settings.rabbitmq.host, settings.rabbitmq.port),
        )
        return pika.SelectConnection(
            parameters=pika.ConnectionParameters(
                host=settings.rabbitmq.host,
                port=settings.rabbitmq.port,
                virtual_host='/',
                credentials=pika.PlainCredentials(
                    username=settings.rabbitmq.user,
                    password=settings.rabbitmq.password,
                ),
                heartbeat=30,
            ),
            on_open_callback=self.on_connection_open,
            on_open_error_callback=self.on_connection_open_error,
            on_close_callback=self.on_connection_closed,
        )

    def on_connection_open(self, _unused_connection):
        """This method is called by pika once the connection to RabbitMQ has
        been established. It passes the handle to the connection object in
        case we need it, but in this case, we'll just mark it unused.

        :param pika.SelectConnection _unused_connection: The connection

        """
        logger.info(
            '{}: RabbitMQ select loop interactor: Connection opened',
            self._consumer_worker_name,
        )
        self.open_channel()

    def on_connection_open_error(self, _unused_connection, err):
        """This method is called by pika if the connection to RabbitMQ
        can't be established.

        :param pika.SelectConnection _unused_connection: The connection
        :param Exception err: The error

        """
        logger.error(
            (
                '{}: RabbitMQ select loop interactor: Connection open failed,'
                ' reopening in 5 seconds: {}'
            ),
            self._consumer_worker_name,
            err,
        )
        self._connection.ioloop.call_later(5, self._connection.ioloop.stop)

    def on_connection_closed(self, _unused_connection, reason):
        """This method is invoked by pika when the connection to RabbitMQ is
        closed unexpectedly. Since it is unexpected, we will reconnect to
        RabbitMQ if it disconnects.

        :param pika.connection.Connection connection: The closed connection obj
        :param Exception reason: exception representing reason for loss of
            connection.

        """
        self._channel = None
        if self._stopping:
            self._connection.ioloop.stop()
        else:
            if ('200' and 'Normal shutdown' in reason.__repr__()) or (
                'SelfExitException' in reason.__repr__()
            ):
                logger.warning(
                    ('{}: RabbitMQ select loop interactor: Connection' ' closed: {}'),
                    self._consumer_worker_name,
                    reason,
                )
            else:
                logger.warning(
                    (
                        '{}: RabbitMQ select loop interactor: Connection'
                        ' closed, reopening in 5 seconds: {}'
                    ),
                    self._consumer_worker_name,
                    reason,
                )
                self._connection.ioloop.call_later(
                    5,
                    self._connection.ioloop.stop,
                )

    def open_channel(self):
        """This method will open a new channel with RabbitMQ by issuing the
        Channel.Open RPC command. When RabbitMQ confirms the channel is open
        by sending the Channel.OpenOK RPC reply, the on_channel_open method
        will be invoked.

        """
        logger.info(
            '{}: RabbitMQ select loop interactor: Creating a new channel',
            self._consumer_worker_name,
        )
        self._connection.channel(on_open_callback=self.on_channel_open)

    def on_channel_open(self, channel):
        """This method is invoked by pika when the channel has been opened.
        The channel object is passed in so we can make use of it.

        Since the channel is now open, we'll declare the exchange to use.

        :param pika.channel.Channel channel: The channel object

        """
        logger.info(
            '{}: RabbitMQ select loop interactor: Channel opened',
            self._consumer_worker_name,
        )
        self._channel = channel
        self.add_on_channel_close_callback()
        # self.setup_exchange(self.exchange)
        try:
            self.start_publishing()
            if self._consume_queue and self._consume_callback:
                self.start_consuming(
                    queue_name=self._consume_queue,
                    consume_cb=self._consume_callback,
                    auto_ack=False,
                )
        except Exception as err:
            logger.opt(exception=True).error(
                (
                    '{}: RabbitMQ select loop interactor: Failed'
                    ' on_channel_open hook with error_msg: {}'
                ),
                self._consumer_worker_name,
                str(err),
            )
            # must be raised back to caller to be handled there
            raise err

    def add_on_channel_close_callback(self):
        """This method tells pika to call the on_channel_closed method if
        RabbitMQ unexpectedly closes the channel.

        """
        logger.info(
            ('{}: RabbitMQ select loop interactor: Adding channel close' ' callback'),
            self._consumer_worker_name,
        )
        self._channel.add_on_close_callback(self.on_channel_closed)

    def on_channel_closed(self, channel, reason):
        """Invoked by pika when RabbitMQ unexpectedly closes the channel.
        Channels are usually closed if you attempt to do something that
        violates the protocol, such as re-declare an exchange or queue with
        different parameters. In this case, we'll close the connection
        to shutdown the object.

        :param pika.channel.Channel channel: The closed channel
        :param Exception reason: why the channel was closed

        """
        logger.warning(
            '{}: RabbitMQ select loop interactor: Channel {} was closed: {}',
            self._consumer_worker_name,
            channel,
            reason,
        )
        self._channel = None
        try:
            self._connection.close()
        except Exception as e:
            if (
                isinstance(e, pika.exceptions.ConnectionWrongStateError) and
                'Illegal close' in e.__repr__() and
                'connection state=CLOSED' in e.__repr__()
            ):
                logger.error(
                    (
                        '{}: RabbitMQ select loop interactor: Tried closing'
                        ' connection that was already closed on channel close'
                        ' callback. Exception: {}. Will close ioloop now.'
                    ),
                    self._consumer_worker_name,
                    e,
                )
            else:
                logger.opt(exception=True).error(
                    (
                        '{}: RabbitMQ select loop interactor: Exception closing'
                        ' connection on channel close callback: {}. Will close'
                        ' ioloop now.'
                    ),
                    self._consumer_worker_name,
                    e,
                )
            self._connection.ioloop.stop()

    def start_publishing(self):
        """This method will enable delivery confirmations and schedule the
        first message to be sent to RabbitMQ

        """
        logger.info(
            (
                '{}: RabbitMQ select loop interactor: Issuing consumer related'
                ' RPC commands'
            ),
            self._consumer_worker_name,
        )
        # self.enable_delivery_confirmations()
        self.schedule_next_message()

    def enable_delivery_confirmations(self):
        """Send the Confirm.Select RPC method to RabbitMQ to enable delivery
        confirmations on the channel. The only way to turn this off is to close
        the channel and create a new one.

        When the message is confirmed from RabbitMQ, the
        on_delivery_confirmation method will be invoked passing in a Basic.Ack
        or Basic.Nack method from RabbitMQ that will indicate which messages it
        is confirming or rejecting.

        """
        logger.info(
            (
                '{}: RabbitMQ select loop interactor: Issuing Confirm.Select'
                ' RPC command'
            ),
            self._consumer_worker_name,
        )
        self._channel.confirm_delivery(self.on_delivery_confirmation)

    def on_delivery_confirmation(self, method_frame):
        """Invoked by pika when RabbitMQ responds to a Basic.Publish RPC
        command, passing in either a Basic.Ack or Basic.Nack frame with
        the delivery tag of the message that was published. The delivery tag
        is an integer counter indicating the message number that was sent
        on the channel via Basic.Publish. Here we're just doing house keeping
        to keep track of stats and remove message numbers that we expect
        a delivery confirmation of from the list used to keep track of messages
        that are pending confirmation.

        :param pika.frame.Method method_frame: Basic.Ack or Basic.Nack frame

        """
        confirmation_type = method_frame.method.NAME.split('.')[1].lower()
        logger.info(
            (
                '{}: RabbitMQ select loop interactor: Received {} for delivery'
                ' tag: {}'
            ),
            self._consumer_worker_name,
            confirmation_type,
            method_frame.method.delivery_tag,
        )
        if confirmation_type == 'ack':
            self._acked += 1
        elif confirmation_type == 'nack':
            self._nacked += 1

    def enqueue_msg_delivery(self, exchange, routing_key, msg_body):
        # NOTE: if used in a multi threaded/multi processing context, this will introduce a race condition given that
        #       publish_message() may try to read the queued messages map while it is being concurrently updated by
        #       another process/thread
        self.queued_messages[str(uuid.uuid4())] = [
            msg_body,
            exchange,
            routing_key,
        ]

    def schedule_next_message(self):
        """If we are not closing our connection to RabbitMQ, schedule another
        message to be delivered in PUBLISH_INTERVAL seconds.

        """
        # logger.info('Scheduling next message for %0.1f seconds',
        #             self.PUBLISH_INTERVAL)
        self._connection.ioloop.call_later(
            self.PUBLISH_INTERVAL,
            self.publish_message,
        )

    def publish_message(self):
        """If the class is not stopping, publish a message to RabbitMQ,
        appending a list of deliveries with the message number that was sent.
        This list will be used to check for delivery confirmations in the
        on_delivery_confirmations method.

        Once the message has been sent, schedule another message to be sent.
        The main reason I put scheduling in was just so you can get a good idea
        of how the process is flowing by slowing down and speeding up the
        delivery intervals by changing the PUBLISH_INTERVAL constant in the
        class.

        """
        if self._channel is None or not self._channel.is_open:
            return
        # check for queued messages
        pushed_outputs = list()
        # logger.debug('queued msgs: {}', self.queued_messages)
        try:
            for unique_id in self.queued_messages:
                msg_info = self.queued_messages[unique_id]
                msg, exchange, routing_key = msg_info
                logger.debug(
                    (
                        '{}: RabbitMQ select loop interactor: Got queued'
                        ' message body to send to exchange {} via routing key'
                        ' {}: {}'
                    ),
                    self._consumer_worker_name,
                    exchange,
                    routing_key,
                    msg,
                )
                properties = pika.BasicProperties(
                    delivery_mode=2,
                    content_type='text/plain',
                    content_encoding='utf-8',
                )
                self._channel.basic_publish(
                    exchange=exchange,
                    routing_key=routing_key,
                    body=msg.encode('utf-8'),
                    properties=properties,
                )
                self._message_number += 1
                logger.info(
                    (
                        '{}: RabbitMQ select loop interactor: Published message'
                        ' # {} to exchange {} via routing key {}: {}'
                    ),
                    self._consumer_worker_name,
                    self._message_number,
                    exchange,
                    routing_key,
                    msg,
                )
                pushed_outputs.append(unique_id)
            [self.queued_messages.pop(unique_id) for unique_id in pushed_outputs]
        except Exception as err:
            logger.opt(exception=True).error(
                (
                    '{}: RabbitMQ select loop interactor: Error while'
                    ' publishing message to rabbitmq error_msg: {}, exchange:'
                    ' {}, routing_key: {}, msg: {}'
                ),
                self._consumer_worker_name,
                str(err),
                exchange,
                routing_key,
                msg,
            )
        finally:
            self.schedule_next_message()

    def run(self):
        """Run the example code by connecting and then starting the IOLoop."""
        attempt = 1
        while not self._stopping:
            logger.info(
                (
                    '{}: RabbitMQ interactor select ioloop runner starting |'
                    ' Attempt # {}'
                ),
                self._consumer_worker_name,
                attempt,
            )
            self._connection = None
            self._acked = 0
            self._nacked = 0
            self._message_number = 0
            self._connection = self.connect()
            self._connection.ioloop.start()
            logger.info(
                (
                    '{}: RabbitMQ interactor select ioloop exited in runner'
                    ' loop | Attempt # {}'
                ),
                self._consumer_worker_name,
                attempt,
            )
            attempt += 1
        logger.info(
            '{}: RabbitMQ interactor select ioloop stopped',
            self._consumer_worker_name,
        )

    def close_channel(self):
        """Invoke this command to close the channel with RabbitMQ by sending
        the Channel.Close RPC command.

        """
        if self._channel is not None:
            logger.info(
                '{}: RabbitMQ select loop interactor: Closing the channel',
                self._consumer_worker_name,
            )
            self._channel.close()

    def close_connection(self):
        """This method closes the connection to RabbitMQ."""
        if self._connection is not None:
            logger.info(
                '{}: RabbitMQ select loop interactor: Closing connection',
                self._consumer_worker_name,
            )
            self._connection.close()

    def start_consuming(self, queue_name, consume_cb, auto_ack=False):
        """This method sets up the consumer by first calling
        add_on_cancel_callback so that the object is notified if RabbitMQ
        cancels the consumer. It then issues the Basic.Consume RPC command
        which returns the consumer tag that is used to uniquely identify the
        consumer with RabbitMQ. We keep the value to use it when we want to
        cancel consuming. The on_message method is passed in as a callback pika
        will invoke when a message is fully received.
        """
        logger.info(
            (
                '{}: RabbitMQ select loop interactor: Issuing consumer related'
                ' RPC commands'
            ),
            self._consumer_worker_name,
        )
        self.add_on_cancel_callback()
        self._consumer_tag = self._channel.basic_consume(
            queue=queue_name,
            on_message_callback=consume_cb,
            auto_ack=auto_ack,
        )
        self.was_consuming = True
        self._consuming = True
        # self._channel.start_consuming()

    def add_on_cancel_callback(self):
        """Add a callback that will be invoked if RabbitMQ cancels the consumer
        for some reason. If RabbitMQ does cancel the consumer,
        on_consumer_cancelled will be invoked by pika.
        """
        logger.info(
            (
                '{}: RabbitMQ select loop interactor: Adding consumer'
                ' cancellation callback'
            ),
            self._consumer_worker_name,
        )
        self._channel.add_on_cancel_callback(self.on_consumer_cancelled)

    def on_consumer_cancelled(self, method_frame):
        """Invoked by pika when RabbitMQ sends a Basic.Cancel for a consumer
        receiving messages.
        :param pika.frame.Method method_frame: The Basic.Cancel frame
        """
        logger.info(
            '{}: Consumer was cancelled remotely, shutting down: {}',
            self._consumer_worker_name,
            method_frame,
        )
        if self._channel:
            self._channel.close()

    def stop_consuming(self):
        """Tell RabbitMQ that you would like to stop consuming by sending the
        Basic.Cancel RPC command.
        """
        if self._channel:
            logger.info(
                (
                    '{}: RabbitMQ select loop interactor: Sending a'
                    ' Basic.Cancel RPC command to RabbitMQ'
                ),
                self._consumer_worker_name,
            )
            cb = functools.partial(
                self.on_cancelok,
                userdata=self._consumer_tag,
            )
            self._channel.basic_cancel(self._consumer_tag, cb)

    def on_cancelok(self, _unused_frame, userdata):
        """This method is invoked by pika when RabbitMQ acknowledges the
        cancellation of a consumer. At this point we will close the channel.
        This will invoke the on_channel_closed method once the channel has been
        closed, which will in-turn close the connection.
        :param pika.frame.Method _unused_frame: The Basic.CancelOk frame
        :param str|unicode userdata: Extra user data (consumer tag)
        """
        self._consuming = False
        logger.info(
            (
                '{}: RabbitMQ select loop interactor: RabbitMQ acknowledged the'
                ' cancellation of the consumer: {}'
            ),
            self._consumer_worker_name,
            userdata,
        )
        self.close_channel()

    def stop(self):
        """
        Cleanly shutdown the connection to RabbitMQ by stopping the consumer with RabbitMQ.
        """
        if not self._closing:
            self._closing = True
            self._stopping = True
            logger.info(
                '{}: RabbitMQ select loop interactor: Stopping',
                self._consumer_worker_name,
            )
            if self._consuming:
                self.stop_consuming()
                # self._connection.ioloop.start()
            else:
                self._connection.ioloop.stop()
            logger.info(
                '{}: RabbitMQ select loop interactor: Stopped',
                self._consumer_worker_name,
            )


class RabbitmqThreadedSelectLoopInteractor(object):
    """This is an example publisher/consumer that will handle unexpected interactions
    with RabbitMQ such as channel and connection closures.

    If RabbitMQ closes the connection, it will reopen it. You should
    look at the output, as there are limited reasons why the connection may
    be closed, which usually are tied to permission related issues or
    socket timeouts.

    It uses delivery confirmations and illustrates one way to keep track of
    messages that have been sent and if they've been confirmed by RabbitMQ.

    """

    # interval at which the select loop polls to push out new notifications
    PUBLISH_INTERVAL = 0.01

    def __init__(
        self,
        publish_queue: queue.Queue,
        consume_queue_name=None,
        consume_callback=None,
        consumer_worker_name='',
    ):
        """Setup the example publisher object, passing in the URL we will use
        to connect to RabbitMQ.
        """
        self._connection = None
        self._channel: Union[None, pika.channel.Channel] = None
        self.should_reconnect = False
        self._consumer_worker_name = consumer_worker_name
        self.was_consuming = False
        self._consumer_tag = None
        self.queued_messages: dict = dict()
        self._deliveries = None
        self._acked = None
        self._nacked = None
        self._message_number = None
        self._closing = False
        self._stopping = False
        self._exchange = None
        self._routing_key = None
        self._consuming = False
        self._consume_queue = consume_queue_name
        self._consume_callback = consume_callback
        self._publish_queue = publish_queue

        # In production, experiment with higher prefetch values
        # for higher consumer throughput
        self._prefetch_count = 1

    def connect(self):
        """This method connects to RabbitMQ, returning the connection handle.
        When the connection is established, the on_connection_open method
        will be invoked by pika.

        :rtype: pika.SelectConnection

        """
        self._logger.info(
            'Creating RabbitMQ threaded select ioloop connection to {}',
            (settings.rabbitmq.host, settings.rabbitmq.port),
        )
        return pika.SelectConnection(
            parameters=pika.ConnectionParameters(
                host=settings.rabbitmq.host,
                port=settings.rabbitmq.port,
                virtual_host='/',
                credentials=pika.PlainCredentials(
                    username=settings.rabbitmq.user,
                    password=settings.rabbitmq.password,
                ),
                heartbeat=30,
            ),
            on_open_callback=self.on_connection_open,
            on_open_error_callback=self.on_connection_open_error,
            on_close_callback=self.on_connection_closed,
        )

    def on_connection_open(self, _unused_connection):
        """This method is called by pika once the connection to RabbitMQ has
        been established. It passes the handle to the connection object in
        case we need it, but in this case, we'll just mark it unused.

        :param pika.SelectConnection _unused_connection: The connection

        """
        self._logger.info(
            'RabbitMQ threaded select loop interactor: Connection opened',
        )
        self.open_channel()

    def on_connection_open_error(self, _unused_connection, err):
        """This method is called by pika if the connection to RabbitMQ
        can't be established.

        :param pika.SelectConnection _unused_connection: The connection
        :param Exception err: The error

        """
        self._logger.error(
            (
                'RabbitMQ threaded select loop interactor: Connection open'
                ' failed, reopening in 5 seconds: {}'
            ),
            err,
        )
        self._connection.ioloop.call_later(5, self._connection.ioloop.stop)

    def on_connection_closed(self, _unused_connection, reason):
        """This method is invoked by pika when the connection to RabbitMQ is
        closed unexpectedly. Since it is unexpected, we will reconnect to
        RabbitMQ if it disconnects.

        :param pika.connection.Connection connection: The closed connection obj
        :param Exception reason: exception representing reason for loss of
            connection.

        """
        self._channel = None
        if self._stopping:
            self._connection.ioloop.stop()
        else:
            if ('200' and 'Normal shutdown' in reason.__repr__()) or (
                'SelfExitException' in reason.__repr__()
            ):
                self._logger.warning(
                    'RabbitMQ select loop interactor: Connection closed: {}',
                    reason,
                )
            else:
                self._logger.warning(
                    (
                        'RabbitMQ select loop interactor: Connection closed,'
                        ' reopening in 5 seconds: {}'
                    ),
                    reason,
                )
                self._connection.ioloop.call_later(
                    5,
                    self._connection.ioloop.stop,
                )

    def open_channel(self):
        """This method will open a new channel with RabbitMQ by issuing the
        Channel.Open RPC command. When RabbitMQ confirms the channel is open
        by sending the Channel.OpenOK RPC reply, the on_channel_open method
        will be invoked.

        """
        self._logger.info(
            'RabbitMQ threaded select loop interactor: Creating a new channel',
        )
        self._connection.channel(on_open_callback=self.on_channel_open)

    def on_channel_open(self, channel):
        """This method is invoked by pika when the channel has been opened.
        The channel object is passed in so we can make use of it.

        Since the channel is now open, we'll declare the exchange to use.

        :param pika.channel.Channel channel: The channel object

        """
        self._logger.info(
            'RabbitMQ threaded select loop interactor: Channel opened',
        )
        self._channel = channel
        self.add_on_channel_close_callback()
        # self.setup_exchange(self.exchange)
        self.start_publishing()
        if self._consume_queue and self._consume_callback:
            self.start_consuming(
                queue_name=self._consume_queue,
                consume_cb=self._consume_callback,
                auto_ack=False,
            )

    def add_on_channel_close_callback(self):
        """This method tells pika to call the on_channel_closed method if
        RabbitMQ unexpectedly closes the channel.

        """
        self._logger.info(
            (
                'RabbitMQ threaded select loop interactor: Adding channel close'
                ' callback'
            ),
        )
        self._channel.add_on_close_callback(self.on_channel_closed)

    def on_channel_closed(self, channel, reason):
        """Invoked by pika when RabbitMQ unexpectedly closes the channel.
        Channels are usually closed if you attempt to do something that
        violates the protocol, such as re-declare an exchange or queue with
        different parameters. In this case, we'll close the connection
        to shutdown the object.

        :param pika.channel.Channel channel: The closed channel
        :param Exception reason: why the channel was closed

        """
        self._logger.warning(
            ('RabbitMQ threaded select loop interactor: Channel {} was' ' closed: {}'),
            channel,
            reason,
        )
        self._channel = None
        try:
            self._connection.close()
        except Exception as e:
            if (
                isinstance(e, pika.exceptions.ConnectionWrongStateError) and
                'Illegal close' in e.__repr__() and
                'connection state=CLOSED' in e.__repr__()
            ):
                self._logger.error(
                    (
                        'RabbitMQ threaded select loop interactor: Tried'
                        ' closing connection that was already closed on channel'
                        ' close callback. Exception: {}. Will close ioloop now.'
                    ),
                    e,
                )
            else:
                self._logger.opt(exception=True).error(
                    (
                        'RabbitMQ threaded select loop interactor: Exception'
                        ' closing connection on channel close callback: {}.'
                        ' Will close ioloop now.'
                    ),
                    e,
                )
                # because on_connection_closed callback would not be reached
                self._connection.ioloop.stop()

    # # # BEGIN - TODO: chain these calls and callbacks to rabbitmq initialization process to definitively init the sys
    #                   low prioritu
    def setup_exchange(self, exchange_name):
        """Setup the exchange on RabbitMQ by invoking the Exchange.Declare RPC
        command. When it is complete, the on_exchange_declareok method will
        be invoked by pika.

        :param str|unicode exchange_name: The name of the exchange to declare

        """
        self._logger.info('Declaring exchange {}', exchange_name)
        # Note: using functools.partial is not required, it is demonstrating
        # how arbitrary data can be passed to the callback when it is called
        cb = functools.partial(
            self.on_exchange_declareok,
            userdata=exchange_name,
        )
        self._channel.exchange_declare(
            exchange=exchange_name,
            exchange_type=self.exchange_TYPE,
            callback=cb,
        )

    def on_exchange_declareok(self, _unused_frame, userdata):
        """Invoked by pika when RabbitMQ has finished the Exchange.Declare RPC
        command.

        :param pika.Frame.Method unused_frame: Exchange.DeclareOk response frame
        :param str|unicode userdata: Extra user data (exchange name)

        """
        self._logger.info('Exchange declared: {}', userdata)
        self.setup_queue(self.QUEUE)

    def setup_queue(self, queue_name):
        """Setup the queue on RabbitMQ by invoking the Queue.Declare RPC
        command. When it is complete, the on_queue_declareok method will
        be invoked by pika.

        :param str|unicode queue_name: The name of the queue to declare.

        """
        self._logger.info('Declaring queue {}', queue_name)
        self._channel.queue_declare(
            queue=queue_name,
            callback=self.on_queue_declareok,
        )

    def on_queue_declareok(self, _unused_frame):
        """Method invoked by pika when the Queue.Declare RPC call made in
        setup_queue has completed. In this method we will bind the queue
        and exchange together with the routing key by issuing the Queue.Bind
        RPC command. When this command is complete, the on_bindok method will
        be invoked by pika.

        :param pika.frame.Method method_frame: The Queue.DeclareOk frame

        """
        self._logger.info(
            'Binding {} to {} with {}',
            self.exchange,
            self.QUEUE,
            self.ROUTING_KEY,
        )
        self._channel.queue_bind(
            self.QUEUE,
            self.exchange,
            routing_key=self.ROUTING_KEY,
            callback=self.on_bindok,
        )

    def on_bindok(self, _unused_frame):
        """This method is invoked by pika when it receives the Queue.BindOk
        response from RabbitMQ. Since we know we're now setup and bound, it's
        time to start publishing."""
        self._logger.info('Queue bound')
        # self.start_publishing()
        self.enable_delivery_confirmations()

    # # # END - TODO: chain these calls and callbacks to rabbitmq initialization process to definitively init the sys
    def start_publishing(self):
        """This method will enable delivery confirmations and schedule the
        first message to be sent to RabbitMQ

        """
        self._logger.info(
            (
                'RabbitMQ threaded select loop interactor: Issuing consumer'
                ' related RPC commands'
            ),
        )
        self.enable_delivery_confirmations()
        self.schedule_next_message()

    def enable_delivery_confirmations(self):
        """Send the Confirm.Select RPC method to RabbitMQ to enable delivery
        confirmations on the channel. The only way to turn this off is to close
        the channel and create a new one.

        When the message is confirmed from RabbitMQ, the
        on_delivery_confirmation method will be invoked passing in a Basic.Ack
        or Basic.Nack method from RabbitMQ that will indicate which messages it
        is confirming or rejecting.

        """
        self._logger.info(
            (
                'RabbitMQ threaded select loop interactor: Issuing'
                ' Confirm.Select RPC command'
            ),
        )
        self._channel.confirm_delivery(self.on_delivery_confirmation)

    def on_delivery_confirmation(self, method_frame):
        """Invoked by pika when RabbitMQ responds to a Basic.Publish RPC
        command, passing in either a Basic.Ack or Basic.Nack frame with
        the delivery tag of the message that was published. The delivery tag
        is an integer counter indicating the message number that was sent
        on the channel via Basic.Publish. Here we're just doing house keeping
        to keep track of stats and remove message numbers that we expect
        a delivery confirmation of from the list used to keep track of messages
        that are pending confirmation.

        :param pika.frame.Method method_frame: Basic.Ack or Basic.Nack frame

        """
        confirmation_type = method_frame.method.NAME.split('.')[1].lower()
        self._logger.info(
            (
                'RabbitMQ threaded select loop interactor: Received {} for'
                ' delivery tag: {}'
            ),
            confirmation_type,
            method_frame.method.delivery_tag,
        )
        if confirmation_type == 'ack':
            self._acked += 1
        elif confirmation_type == 'nack':
            self._nacked += 1
        self._deliveries.remove(method_frame.method.delivery_tag)
        self._logger.info(
            (
                'RabbitMQ threaded select loop interactor: Published {}'
                ' messages, {} have yet to be confirmed, {} were acked and {}'
                ' were nacked'
            ),
            self._message_number,
            len(self._deliveries),
            self._acked,
            self._nacked,
        )

    def schedule_next_message(self, interval=PUBLISH_INTERVAL):
        """If we are not closing our connection to RabbitMQ, schedule another
        message to be delivered in PUBLISH_INTERVAL seconds.

        """
        # self._logger.info('Scheduling next message for %0.1f seconds',
        #             self.PUBLISH_INTERVAL)
        self._connection.ioloop.call_later(interval, self.publish_message)

    def publish_message(self, flush=False):
        """If the class is not stopping, publish a message to RabbitMQ,
        appending a list of deliveries with the message number that was sent.
        This list will be used to check for delivery confirmations in the
        on_delivery_confirmations method.
        """
        if self._channel is None or not self._channel.is_open:
            self._logger.error(
                (
                    'RabbitMQ threaded select loop interactor: Not proceeding'
                    ' with publish queue checks'
                ),
            )
            return
        # check for queued messages
        while True:
            try:
                new_msg = self._publish_queue.get_nowait()
            except queue.Empty:
                if flush:
                    return
            else:
                msg, exchange, routing_key = new_msg
                self._logger.debug(
                    (
                        'RabbitMQ threaded select loop interactor: Got queued'
                        ' message body to send to exchange {} via routing key'
                        ' {}: {}'
                    ),
                    exchange,
                    routing_key,
                    msg,
                )
                properties = pika.BasicProperties(
                    delivery_mode=2,
                    content_type='text/plain',
                    content_encoding='utf-8',
                )
                self._channel.basic_publish(
                    exchange=exchange,
                    routing_key=routing_key,
                    body=msg,  # encoded already
                    properties=properties,
                )
                self._message_number += 1
                self._deliveries.append(self._message_number)
                self._logger.info(
                    (
                        'RabbitMQ threaded select loop interactor: Published'
                        ' message # {} to exchange {} via routing key {}: {}'
                    ),
                    self._message_number,
                    exchange,
                    routing_key,
                    msg,
                )
                self._publish_queue.task_done()
            finally:
                if not flush:
                    self.schedule_next_message()
                    break

    def run(self):
        self._logger = logger.bind(module='Powerloom|RabbitmqHelpers')

        while not self._stopping:
            self._connection = None
            self._deliveries = []
            self._acked = 0
            self._nacked = 0
            self._message_number = 0

            self._connection = self.connect()
            self._connection.ioloop.start()  # blocking
        self._logger.info('RabbitMQ threaded select loop interactor: Stopped')

    def close_channel(self):
        """Invoke this command to close the channel with RabbitMQ by sending
        the Channel.Close RPC command.

        """
        if self._channel is not None:
            self._logger.info(
                'RabbitMQ threaded select loop interactor: Closing the channel',
            )
            self._channel.close()

    def close_connection(self):
        """This method closes the connection to RabbitMQ."""
        if self._connection is not None:
            self._logger.info(
                'RabbitMQ threaded select loop interactor: Closing connection',
            )
            self._connection.close()

    def start_consuming(self, queue_name, consume_cb, auto_ack=False):
        """This method sets up the consumer by first calling
        add_on_cancel_callback so that the object is notified if RabbitMQ
        cancels the consumer. It then issues the Basic.Consume RPC command
        which returns the consumer tag that is used to uniquely identify the
        consumer with RabbitMQ. We keep the value to use it when we want to
        cancel consuming. The on_message method is passed in as a callback pika
        will invoke when a message is fully received.
        """
        self._logger.info(
            (
                'RabbitMQ threaded select loop interactor: Issuing consumer'
                ' related RPC commands'
            ),
        )
        self.add_on_cancel_callback()
        self._consumer_tag = self._channel.basic_consume(
            queue=queue_name,
            on_message_callback=consume_cb,
            auto_ack=auto_ack,
        )
        self.was_consuming = True
        self._consuming = True
        # self._channel.start_consuming()

    def add_on_cancel_callback(self):
        """Add a callback that will be invoked if RabbitMQ cancels the consumer
        for some reason. If RabbitMQ does cancel the consumer,
        on_consumer_cancelled will be invoked by pika.
        """
        self._logger.info(
            (
                'RabbitMQ threaded select loop interactor: Adding consumer'
                ' cancellation callback'
            ),
        )
        self._channel.add_on_cancel_callback(self.on_consumer_cancelled)

    def on_consumer_cancelled(self, method_frame):
        """Invoked by pika when RabbitMQ sends a Basic.Cancel for a consumer
        receiving messages.
        :param pika.frame.Method method_frame: The Basic.Cancel frame
        """
        self._logger.info(
            (
                'RabbitMQ threaded select loop interactor: Consumer was'
                ' cancelled remotely, shutting down: {}'
            ),
            method_frame,
        )
        if self._channel:
            self._channel.close()

    def send_basic_cancel(self):
        """Tell RabbitMQ that you would like to stop consuming by sending the
        Basic.Cancel RPC command. Not to be sent when you are not consuming.
        """
        if self._channel:
            self._logger.info(
                (
                    'RabbitMQ threaded select loop interactor: Sending a'
                    ' Basic.Cancel RPC command to RabbitMQ'
                ),
            )
            cb = functools.partial(
                self.on_cancelok,
                userdata=self._consumer_tag,
            )
            self._channel.basic_cancel(self._consumer_tag, cb)

    def on_cancelok(self, _unused_frame, userdata):
        """This method is invoked by pika when RabbitMQ acknowledges the
        cancellation of a consumer. At this point we will close the channel.
        This will invoke the on_channel_closed method once the channel has been
        closed, which will in-turn close the connection.
        :param pika.frame.Method _unused_frame: The Basic.CancelOk frame
        :param str|unicode userdata: Extra user data (consumer tag)
        """
        self._consuming = False
        self._logger.info(
            (
                'RabbitMQ threaded select loop interactor: RabbitMQ'
                ' acknowledged the cancellation of the consumer: {}'
            ),
            userdata,
        )
        self.close_channel()

    def stop(self):
        """
        Cleanly shutdown the connection to RabbitMQ by stopping the consumer with RabbitMQ.
        """
        if not self._closing:
            self._closing = True
            self._stopping = True
            # try flushing out all queued messages
            self._logger.info(
                (
                    'RabbitMQ threaded select loop interactor: attempting to'
                    ' send out queued messages before stopping ioloop and'
                    ' disconnecting'
                ),
            )
            try:
                self.publish_message(flush=True)
            except:
                pass
            # if consuming flag was set internally, the clean way to exit for a consumer is to bfirst send basic
            # self.send_basic_cancel()
            self.close_channel()


def main():
    # Connect to localhost:5672 as guest with the password guest and virtual host "/" (%2F)
    example = RabbitmqSelectLoopInteractor(
        'amqp://guest:guest@localhost:5672/%2F?connection_attempts=3&heartbeat=3600',
    )
    example.run()


if __name__ == '__main__':
    main()
