import signal

from dynaconf import settings
from setproctitle import setproctitle

from default_logger import logger
from exceptions import GenericExitOnSignal
from init_rabbitmq import init_exchanges_queues
from process_hub_core import ProcessHubCore


def generic_exit_handler(signum, frame):
    raise GenericExitOnSignal


def main():
    for signame in [signal.SIGINT, signal.SIGTERM, signal.SIGQUIT]:
        signal.signal(signame, generic_exit_handler)
    setproctitle(f'PowerLoom|UniswapPoolerProcessHub|Core|Launcher:{settings.NAMESPACE}-{settings.INSTANCE_ID[:5]}')

    # setup logging
    launcher_logger = logger.bind(module='PowerLoom|UniswapPoolerProcessHub|Core|Launcher', namespace=settings.NAMESPACE, instance_id=settings.INSTANCE_ID[:5])

    init_exchanges_queues()
    p_name = f'PowerLoom|UniswapPoolerProcessHub|Core-{settings.INSTANCE_ID[:5]}'
    core = ProcessHubCore(name=p_name)
    core.start()
    launcher_logger.debug('Launched %s with PID %s', p_name, core.pid)
    try:
        launcher_logger.debug(
            '%s Launcher still waiting on core to join...', p_name
        )
        core.join()
    except GenericExitOnSignal:
        launcher_logger.debug('%s Launcher received SIGTERM. Will attempt to join with ProcessHubCore process...', p_name)
    finally:
        try:
            launcher_logger.debug(
                '%s Launcher still waiting on core to join...', p_name
            )
            core.join()
        except Exception as e:
            launcher_logger.info(
                '%s Launcher caught exception still waiting on core to join... %s',
                p_name, e
            )
        launcher_logger.debug(
            '%s Launcher found alive status of core: %s', p_name, core.is_alive()
        )


if __name__ == '__main__':
    main()

