from init_rabbitmq import init_exchanges_queues
from process_hub_core import ProcessHubCore
import logging
import logging.handlers
import signal
from setproctitle import setproctitle



class SIGTERMExit(Exception):
    pass


def sigterm_handler(signum, frame):
    raise SIGTERMExit


def main():
    signal.signal(signal.SIGTERM, sigterm_handler)
    # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|ProcessHub|Core|Launcher'))
    # logging.config.dictConfig(config_logger_with_namespace(namespace=None))
    setproctitle(f'PowerLoom|UniswapPoolerProcessHub|Core|Launcher')
    logger = logging.getLogger('PowerLoom|UniswapPoolerProcessHub|Core|Launcher')
    logger.setLevel(logging.DEBUG)
    logger.handlers = [logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]
    init_exchanges_queues()
    core = ProcessHubCore(name='PowerLoom|UniswapPoolerProcessHub|Core')
    core.start()
    logger.debug('Launched PowerLoom|UniswapPoolerProcessHub|Core with PID %s', core.pid)
    try:
        core.join()
    except KeyboardInterrupt:
        logger.debug('PowerLoom|UniswapPoolerProcessHub|Core Launcher received SIGINT. Will attempt to join with ProcessHubCore process...')
    except SIGTERMExit:
        logger.debug('PowerLoom|UniswapPoolerProcessHub|Core Launcher received SIGTERM. Will attempt to join with ProcessHubCore process...')
    finally:
        try:
            core.join()
        except:
            pass
        logger.debug('PowerLoom|UniswapPoolerProcessHub|Core Launcher exiting. ProcessHubCore exited and joined with parent process...')


if __name__ == '__main__':
    main()

