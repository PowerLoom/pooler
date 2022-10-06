from logging import handlers
from gunicorn.app.base import BaseApplication
from gunicorn.glogging import Logger
from loguru import logger
from dynaconf import settings
from log_fetch_service import app
from gunicorn_core_launcher import StubbedGunicornLogger, StandaloneApplication
import os
import logging
import sys

LOG_LEVEL = logging.getLevelName(os.environ.get("LOG_LEVEL", "DEBUG"))
JSON_LOGS = True if os.environ.get("JSON_LOGS", "0") == "1" else False
WORKERS = int(os.environ.get("GUNICORN_WORKERS", "5"))


class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        if 'PowerLoom' not in record.name:
            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())
        else:
            logging.getLogger(record.name).handle(record)


if __name__ == '__main__':
    intercept_handler = InterceptHandler()
    logging.root.setLevel(LOG_LEVEL)

    seen = set()
    for name in [
        *logging.root.manager.loggerDict.keys(),
        "gunicorn",
        "gunicorn.access",
        "gunicorn.error",
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
    ]:
        if name not in seen:
            if 'PowerLoom' not in name:
                seen.add(name.split(".")[0])
                logging.getLogger(name).handlers = [intercept_handler]
            else:
                logging.getLogger(name).handlers = [logging.handlers.SocketHandler(host=settings.get('LOGGING_SERVER.HOST','localhost'),
            port=settings.get('LOGGING_SERVER.PORT',logging.handlers.DEFAULT_TCP_LOGGING_PORT))]
    # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|EthLogs|RequestAPI'))

    logger.configure(handlers=[
        {"sink": sys.stdout, "serialize": JSON_LOGS, "level": logging.DEBUG},
        {"sink": sys.stderr, "serialize": JSON_LOGS, "level": logging.ERROR}
    ])
    # logger.add(logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT), level=logging.DEBUG)
    options = {
        "bind": f"{settings.ETH_LOG_WORKER.HOST}:{settings.ETH_LOG_WORKER.PORT}",
        "workers": WORKERS,
        "accesslog": "-",
        "errorlog": "-",
        "worker_class": "uvicorn.workers.UvicornWorker",
        "logger_class": StubbedGunicornLogger
    }

    StandaloneApplication(app, options).run()
