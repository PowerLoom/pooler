from typing import Union
from loguru import logger
import logging.handlers


# #BEGIN  legacy logging config for central logging server to use loguru logging interceptor
class actorLogFilter(logging.Filter):
    def filter(self, logrecord):
        b = 'actorAddress' in logrecord.__dict__
        # print('Got log record in actorLogFilter and filter result: ', logrecord, b)
        return b


class notActorLogFilter(logging.Filter):
    def filter(self, logrecord):
        b = 'actorAddress' not in logrecord.__dict__
        # print('Got log record in notActorLogFilter and filter result: ', logrecord. b)
        return b

# logging.config.dictConfig(
    #     {
    #         'version': 1,
    #         'formatters': {
    #             'normal': {'format': '%(levelname)-8s %(name)-4s  %(asctime)s: %(message)s'},
    #             'actor': {
    #                 'format': '%(levelname)-8s %(actorAddress)-4s %(asctime)s: %(message)s'
    #             }
    #         },
    #         'filters': {
    #             'isActorLog': {'()': actorLogFilter},
    #             'notActorLog': {'()': notActorLogFilter}
    #         },
    #         'handlers': {
    #             'h1': {
    #                 'class': 'proto_system_logging_server.InterceptHandler',
    #                 'level': logging.DEBUG,
    #                 'filters': ['isActorLog'],
    #                 'formatter': 'actor'
    #             },
    #             'h2': {
    #                 'class': 'proto_system_logging_server.InterceptHandler',
    #                 'level': logging.DEBUG,
    #                 'filters': ['notActorLog'],
    #                 'formatter': 'normal'
    #             },
    #             'h3': {
    #                 'class': 'proto_system_logging_server.InterceptHandler',
    #                 'level': logging.ERROR,
    #                 'filters': ['notActorLog'],
    #                 'formatter': 'normal'
    #             },
    #             'h4': {
    #                 'class': 'proto_system_logging_server.InterceptHandler',
    #                 'level': logging.ERROR,
    #                 'filters': ['isActorLog'],
    #                 'formatter': 'actor'
    #             },
    #         },
    #         'loggers': {'': {'handlers': ['h1', 'h2', 'h3', 'h4'], 'level': logging.DEBUG}}
    #     }
    # )

# #END  legacy logging config for central logging server to use loguru logging interceptor


def config_logger_with_namespace(namespace: Union[str, None], remove_root_config=True) -> dict:
    log_cfg = {
        'version': 1,
        'handlers': {
            'socketHandler': {
                'class': 'logging.handlers.SocketHandler',
                'level': logging.DEBUG,
                'host': 'localhost',
                'port': logging.handlers.DEFAULT_TCP_LOGGING_PORT
            },
        },
        'loggers': {'root': {'handlers': ['socketHandler'], 'level': logging.DEBUG}}
    }
    if not namespace:
        return log_cfg
    else:
        log_cfg['loggers'][namespace] = log_cfg['loggers']['root']
        if remove_root_config:
            del log_cfg['loggers']['root']
        # print(log_cfg)
        return log_cfg


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

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_loguru_intercept():
    intercept_handler = InterceptHandler()
    # logging.basicConfig(handlers=[intercept_handler], level=LOG_LEVEL)
    # logging.root.handlers = [intercept_handler]
    logging.root.setLevel(logging.DEBUG)

    seen = set()
    for name in [
        *logging.root.manager.loggerDict.keys(),
    ]:
        if name not in seen:
            seen.add(name.split(".")[0])
            logging.getLogger(name).handlers = [intercept_handler]