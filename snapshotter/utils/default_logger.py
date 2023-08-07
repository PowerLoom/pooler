from loguru import logger

from snapshotter.settings.config import settings

# {extra} field can be used to pass extra parameters to the logger using .bind()
FORMAT = '{time:MMMM D, YYYY > HH:mm:ss!UTC} | {level} | {message} | {extra}'


def trace_enabled(_):
    return settings.logs.trace_enabled


def logger_filter_trace(record):
    if record['level'].name == 'TRACE':
        return True
    return False


def logger_filter_debug(record):
    if record['level'].name == 'DEBUG':
        return True
    return False


def logger_filter_info(record):
    if record['level'].name == 'INFO':
        return True
    return False


def logger_filter_success(record):
    if record['level'].name == 'SUCCESS':
        return True
    return False


def logger_filter_warning(record):
    if record['level'].name == 'WARNING':
        return True
    return False


def logger_filter_error(record):
    if record['level'].name == 'ERROR':
        return True
    return False


def logger_filter_critical(record):
    if record['level'].name == 'CRITICAL':
        return True
    return False


logger.remove()

if settings.logs.write_to_files:
    logger.add(
        'logs/debug.log', level='DEBUG', format=FORMAT, filter=logger_filter_debug,
        rotation='6 hours', compression='tar.xz', retention='2 days',
    )
    logger.add(
        'logs/info.log', level='INFO', format=FORMAT, filter=logger_filter_info,
        rotation='6 hours', compression='tar.xz', retention='2 days',
    )
    logger.add(
        'logs/success.log', level='SUCCESS', format=FORMAT, filter=logger_filter_success,
        rotation='6 hours', compression='tar.xz', retention='2 days',
    )
    logger.add(
        'logs/warning.log', level='WARNING', format=FORMAT, filter=logger_filter_warning,
        rotation='6 hours', compression='tar.xz', retention='2 days',
    )
    logger.add(
        'logs/error.log', level='ERROR', format=FORMAT, filter=logger_filter_error,
        rotation='6 hours', compression='tar.xz', retention='2 days',
    )
    logger.add(
        'logs/critical.log', level='CRITICAL', format=FORMAT, filter=logger_filter_critical,
        rotation='6 hours', compression='tar.xz', retention='2 days',
    )
    logger.add(
        'logs/trace.log', level='TRACE', format=FORMAT, filter=logger_filter_trace,
        rotation='6 hours', compression='tar.xz', retention='2 days',
    )
