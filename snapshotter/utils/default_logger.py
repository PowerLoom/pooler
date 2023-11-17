from loguru import logger

from snapshotter.settings.config import settings

# {extra} field can be used to pass extra parameters to the logger using .bind()
FORMAT = '{time:MMMM D, YYYY > HH:mm:ss!UTC} | {level} | {message} | {extra}'


def trace_enabled(_):
    """
    Returns the value of trace_enabled setting from the settings module.

    Args:
        _: Unused argument.

    Returns:
        bool: The value of trace_enabled setting.
    """
    return settings.logs.trace_enabled


def logger_filter_trace(record):
    """
    Filter function for logging records with level 'TRACE'.

    Args:
        record (dict): The logging record to be filtered.

    Returns:
        bool: True if the record's level is 'TRACE', False otherwise.
    """
    if record['level'].name == 'TRACE':
        return True
    return False


def logger_filter_debug(record):
    """
    Filter function to be used with Python's logging module to filter out log records with level lower than DEBUG.

    Args:
        record (logging.LogRecord): The log record to be filtered.

    Returns:
        bool: True if the log record's level is DEBUG, False otherwise.
    """
    if record['level'].name == 'DEBUG':
        return True
    return False


def logger_filter_info(record):
    """
    Filter function for logger to only allow INFO level logs.

    Args:
        record (dict): The log record to be filtered.

    Returns:
        bool: True if the log record is INFO level, False otherwise.
    """
    if record['level'].name == 'INFO':
        return True
    return False


def logger_filter_success(record):
    """
    Filter function to only allow records with level 'SUCCESS'.

    Args:
        record (dict): The log record to filter.

    Returns:
        bool: True if the record's level is 'SUCCESS', False otherwise.
    """
    if record['level'].name == 'SUCCESS':
        return True
    return False


def logger_filter_warning(record):
    """
    Filter function to only allow warning level logs through.

    Args:
        record (dict): The log record to filter.

    Returns:
        bool: True if the log record is a warning level log, False otherwise.
    """
    if record['level'].name == 'WARNING':
        return True
    return False


def logger_filter_error(record):
    """
    Filter function to only allow ERROR level logs to be processed.

    Args:
        record (dict): The log record to be filtered.

    Returns:
        bool: True if the log record is an ERROR level log, False otherwise.
    """
    if record['level'].name == 'ERROR':
        return True
    return False


def logger_filter_critical(record):
    """
    Filter function to only allow records with CRITICAL level.

    Args:
        record (dict): The log record to be filtered.

    Returns:
        bool: True if the record's level is CRITICAL, False otherwise.
    """
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
