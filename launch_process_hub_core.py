from init_rabbitmq import init_exchanges_queues
from process_hub_core import ProcessHubCore
from setproctitle import setproctitle
from exceptions import GenericExitOnSignal
import sys
import logging
import logging.handlers
import signal
from dynaconf import settings


def generic_exit_handler(signum, frame):
    raise GenericExitOnSignal


def main():
    for signame in [signal.SIGINT, signal.SIGTERM, signal.SIGQUIT]:
        signal.signal(signame, generic_exit_handler)
    # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|ProcessHub|Core|Launcher'))
    # logging.config.dictConfig(config_logger_with_namespace(namespace=None))
    setproctitle(f'PowerLoom|UniswapPoolerProcessHub|Core|Launcher:{settings.NAMESPACE}-{settings.INSTANCE_ID[:5]}')
    logger = logging.getLogger(f'PowerLoom|UniswapPoolerProcessHub|Core|Launcher:{settings.NAMESPACE}-{settings.INSTANCE_ID}')
    logger.setLevel(logging.DEBUG)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    logger.handlers = [
        logging.handlers.SocketHandler(host=settings.get('LOGGING_SERVER.HOST','localhost'),
            port=settings.get('LOGGING_SERVER.PORT',logging.handlers.DEFAULT_TCP_LOGGING_PORT)),
        stdout_handler, stderr_handler
    ]
    init_exchanges_queues()
    p_name = f'PowerLoom|UniswapPoolerProcessHub|Core-{settings.INSTANCE_ID[:5]}'
    core = ProcessHubCore(name=p_name)
    core.start()
    logger.debug('Launched %s with PID %s', p_name, core.pid)
    try:
        logger.debug(
            '%s Launcher still waiting on core to join...', p_name
        )
        core.join()
    except GenericExitOnSignal:
        logger.debug('%s Launcher received SIGTERM. Will attempt to join with ProcessHubCore process...', p_name)
    finally:
        try:
            logger.debug(
                '%s Launcher still waiting on core to join...', p_name
            )
            core.join()
        except Exception as e:
            logger.info(
                '%s Launcher caught exception still waiting on core to join... %s',
                p_name, e
            )
        logger.debug(
            '%s Launcher found alive status of core: %s', p_name, core.is_alive()
        )


if __name__ == '__main__':
    main()

