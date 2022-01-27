from init_rabbitmq import init_exchanges_queues
from process_hub_core import ProcessHubCore
from proto_system_logging import config_logger_with_namespace
import logging
import logging.handlers
import signal



class SIGTERMExit(Exception):
    pass


def sigterm_handler(signum, frame):
    raise SIGTERMExit


def main():
    signal.signal(signal.SIGTERM, sigterm_handler)
    # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|ProcessHub|Core|Launcher'))
    # logging.config.dictConfig(config_logger_with_namespace(namespace=None))
    logger = logging.getLogger('PowerLoom|ProcessHub|Core|Launcher')
    logger.setLevel(logging.DEBUG)
    logger.handlers = [logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]
    init_exchanges_queues()
    core = ProcessHubCore(name='PowerLoomProcessHubCore')
    core.start()
    logger.debug('Launched ProcessHubCore with PID %s', core.pid)
    try:
        core.join()
    except KeyboardInterrupt:
        logger.debug('ProcessHubCore Launcher received SIGINT. Will attempt to join with ProcessHubCore process...')
    except SIGTERMExit:
        logger.debug('ProcessHubCore Launcher received SIGTERM. Will attempt to join with ProcessHubCore process...')
    finally:
        try:
            core.join()
        except:
            pass
        logger.debug('ProcessHubCore Launcher exiting. ProcessHubCore exited and joined with parent process...')


if __name__ == '__main__':
    main()

