import logging
import os

from gunicorn.app.base import BaseApplication
from gunicorn.glogging import Logger

from snapshotter.utils.default_logger import logger

LOG_LEVEL = logging.getLevelName(os.environ.get('LOG_LEVEL', 'DEBUG'))


class InterceptHandler(logging.Handler):
    """
    A custom logging handler that intercepts log records and forwards them to Loguru logger.
    """

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

        logger.opt(depth=depth, exception=record.exc_info).log(
            level,
            record.getMessage(),
        )


class StubbedGunicornLogger(Logger):
    """
    A custom logger for Gunicorn that stubs out the error and access loggers.

    This logger sets up a NullHandler for both the error and access loggers, effectively
    disabling them. It also sets the log level to the value of LOG_LEVEL, which is defined
    elsewhere in the codebase.
    """

    def setup(self, cfg):
        handler = logging.NullHandler()
        self.error_logger = logging.getLogger('gunicorn.error')
        self.error_logger.addHandler(handler)
        self.access_logger = logging.getLogger('gunicorn.access')
        self.access_logger.addHandler(handler)
        self.error_log.setLevel(LOG_LEVEL)
        self.access_log.setLevel(LOG_LEVEL)


class StandaloneApplication(BaseApplication):
    """
    A standalone Gunicorn application that can be run without a Gunicorn server.
    """

    def __init__(self, app, options=None):
        """
        Initialize the Gunicorn server with the given app and options.

        :param app: The WSGI application to run.
        :type app: callable
        :param options: Optional dictionary of configuration options.
        :type options: dict
        """
        self.options = options or {}
        self.application = app
        super().__init__()

    def load_config(self):
        """
        Load the configuration for the Gunicorn server.

        This function loads the configuration for the Gunicorn server from the options
        provided by the user. It sets the configuration values in the `cfg` object.

        :return: None
        """
        config = {
            key: value
            for key, value in self.options.items()
            if key in self.cfg.settings and value is not None
        }
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        """
        Load the application and return it.
        """
        return self.application
