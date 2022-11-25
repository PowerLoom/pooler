from loguru import logger
import pickle
import socketserver
import struct
import logging
import logging.handlers
import logging.config
import sys
from dynaconf import settings


class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # print(record.__dict__)
        # Find caller from where originated the logged message
        # For calls coming in from libraries, check the process name and adjust accordingly
        if not ('PowerLoom' in record.__dict__['name'] or
                (
                        record.__dict__['name'] == 'root' and
                        ('PowerLoom' in record.__dict__['processName'] )
                )
        ):
            return
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        if record.__dict__['name'] == 'root':
            pre_log = logger.opt(depth=depth, exception=record.exc_info).patch(
                lambda rec: rec.update(name=record.__dict__['processName']+':'+record.__dict__['funcName']))
        else:
            pre_log = logger.opt(depth=depth, exception=record.exc_info).patch(
                lambda rec: rec.update(name=record.__dict__['name']))
        pre_log.log(level, record.getMessage())
        # # legacy thespian actor system logging support
        # else:
        #     pre_log = logger.opt(depth=depth, exception=record.exc_info).patch(lambda rec: rec.update(name=record.__dict__['actorAddress']))


class LogRecordStreamHandler(socketserver.StreamRequestHandler):
    """Handler for a streaming logging request.

    This basically logs the record using whatever logging policy is
    configured locally.
    """

    def handle(self):
        """
        Handle multiple requests - each expected to be a 4-byte length,
        followed by the LogRecord in pickle format. Logs the record
        according to whatever policy is configured locally.
        """
        while True:
            chunk = self.connection.recv(4)
            if len(chunk) < 4:
                break
            slen = struct.unpack('>L', chunk)[0]
            chunk = self.connection.recv(slen)
            while len(chunk) < slen:
                chunk = chunk + self.connection.recv(slen - len(chunk))
            obj = self.unPickle(chunk)
            record = logging.makeLogRecord(obj)
            self.handleLogRecord(record)

    def unPickle(self, data):
        return pickle.loads(data)

    def handleLogRecord(self, record):
        if self.server.logname is not None:
            # print('Got logger name from self.server.logname')
            name = self.server.logname
        else:
            # print('Got logger name from logRecord obj')
            name = record.name
        # print('Got logger name used to send the call: ', name)
        logger_ = logging.getLogger(name)
        # N.B. EVERY record gets logged. This is because Logger.handle
        # is normally called AFTER logger-level filtering. If you want
        # to do filtering, do it at the client end to save wasting
        # cycles and network bandwidth!
        logger_.handle(record)


class LogRecordSocketReceiver(socketserver.ThreadingTCPServer):
    """
    Simple TCP socket-based logging receiver suitable for testing.
    """
    allow_reuse_address = True

    def __init__(self, host=settings.get('LOGGING_SERVER.HOST','localhost'),
            port=settings.get('LOGGING_SERVER.PORT',logging.handlers.DEFAULT_TCP_LOGGING_PORT),
                 handler=LogRecordStreamHandler):
        socketserver.ThreadingTCPServer.__init__(self, (host, port), handler)
        self.abort = 0
        self.timeout = 1
        self.logname = None

    def serve_until_stopped(self):
        import select
        abort = 0
        while not abort:
            rd, wr, ex = select.select([self.socket.fileno()],
                                       [], [],
                                       self.timeout)
            if rd:
                self.handle_request()
            abort = self.abort


# def trade_volume_msg_filter(record):
#     print(record)
#     return 'TradeVolume' in record['extra']['third_party_module']


def main():
    logger.remove()
    logging.basicConfig(handlers=[InterceptHandler()], level=0)
    normal_format = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level> "
    err_format = "<red>{time:YYYY-MM-DD HH:mm:ss.SSS}</red> | <level>{level: <8}</level> | <white>{name}</white> - <level>{message}</level> "
    logger.configure(
        handlers=[
            {"sink": sys.stdout, "level": logging.DEBUG, "format": normal_format},
            {"sink": sys.stderr, "level": logging.ERROR, "format": err_format},
            # {
            #     "sink": "logs/TradeVolumeEvents_{time}",
            #     "level": logging.DEBUG,
            #     "format": normal_format,
            #     "rotation": '20MB',
            #     "retention": 20,
            #     "compression": 'gz',
            #     "filter": trade_volume_msg_filter
            # }
        ],
        # extra={'third_party_module': 'Core'}
    )
    tcpserver = LogRecordSocketReceiver()
    print('About to start TCP server...')
    tcpserver.serve_until_stopped()


if __name__ == '__main__':
    main()
