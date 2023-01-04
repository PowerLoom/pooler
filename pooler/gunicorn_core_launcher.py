import logging
import os
import sys

from dynaconf import settings
from loguru import logger

from pooler.core_api import app
from pooler.utils.gunicorn import InterceptHandler
from pooler.utils.gunicorn import StandaloneApplication
from pooler.utils.gunicorn import StubbedGunicornLogger

LOG_LEVEL = logging.getLevelName(os.environ.get('LOG_LEVEL', 'DEBUG'))
JSON_LOGS = True if os.environ.get('JSON_LOGS', '0') == '1' else False
WORKERS = int(os.environ.get('GUNICORN_WORKERS', '5'))


if __name__ == '__main__':
    intercept_handler = InterceptHandler()
    # logging.basicConfig(handlers=[intercept_handler], level=LOG_LEVEL)
    # logging.root.handlers = [intercept_handler]
    logging.root.setLevel(LOG_LEVEL)

    seen = set()
    for name in [
        *logging.root.manager.loggerDict.keys(),
        'gunicorn',
        'gunicorn.access',
        'gunicorn.error',
        'uvicorn',
        'uvicorn.access',
        'uvicorn.error',
    ]:
        if name not in seen:
            seen.add(name.split('.')[0])
            logging.getLogger(name).handlers = [intercept_handler]

    logger.configure(
        handlers=[
            {'sink': sys.stdout, 'serialize': JSON_LOGS, 'level': logging.DEBUG},
            {'sink': sys.stderr, 'serialize': JSON_LOGS, 'level': logging.ERROR},
        ],
    )

    options = {
        'bind': f'{settings.HOST}:{settings.PORT}',
        'workers': WORKERS,
        'accesslog': '-',
        'errorlog': '-',
        'worker_class': 'uvicorn.workers.UvicornWorker',
        'logger_class': StubbedGunicornLogger,
    }

    StandaloneApplication(app, options).run()
