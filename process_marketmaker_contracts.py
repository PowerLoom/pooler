from multiprocessing import Process
from dynaconf import settings
from uniswap_functions import get_all_pairs_and_write_to_file
import setproctitle
import time
import psutil

""" Initialize the loggers """

REDIS_CONN_CONF = {
    "host": settings['REDIS']['HOST'],
    "port": settings['REDIS']['PORT'],
    "password": settings['REDIS']['PASSWORD'],
    "db": settings['REDIS']['DB']
}


def main():
    setproctitle.setproctitle('PowerLoom|MarketMakerProcessor|Main')
    worker = None
    while True:
        if not worker:
            worker = Process(target=get_all_pairs_and_write_to_file)
            worker.start()
        else:
            p = psutil.Process(pid=worker.pid)
            if p.status() != psutil.STATUS_RUNNING:
                worker = None
                continue
        time.sleep(settings.UPDATE_PAIRS_INTERVAL)


if __name__ == '__main__':
    main()
