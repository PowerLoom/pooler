import sys
import traceback

from loguru import logger

from pooler.settings.config import settings

# {extra} field can be used to pass extra parameters to the logger using .bind()
FORMAT = '{time:MMMM D, YYYY > HH:mm:ss!UTC} | {level} | {message}| {extra}'


def trace_enabled(_):
    return settings.logs.trace_enabled


logger.remove(0)

logger.add(sys.stdout, level='DEBUG', format=FORMAT)
logger.add(sys.stderr, level='WARNING', format=FORMAT)
logger.add(
    sys.stderr,
    level='ERROR',
    format=FORMAT,
    backtrace=True,
    diagnose=True,
)
logger.add(
    sys.stdout,
    level='TRACE',
    format=FORMAT,
    filter=trace_enabled,
    backtrace=True,
    diagnose=True,
)

if settings.logs.write_to_files:
    logger.add('logs/debug.log', level='DEBUG', format=FORMAT, rotation='1 day')
    logger.add(
        'logs/warning.log',
        level='WARNING',
        format=FORMAT,
        rotation='1 day',
    )
    logger.add(
        'logs/error.log',
        level='ERROR',
        format=FORMAT,
        backtrace=True,
        rotation='1 day',
    )
    logger.add(
        'logs/trace.log',
        level='TRACE',
        format=FORMAT,
        filter=trace_enabled,
        backtrace=True,
        rotation='1 day',
    )


# taken from https://stackoverflow.com/questions/6086976/how-to-get-a-complete-exception-stack-trace-in-python#16589622
def format_exception(e):
    exception_list = traceback.format_stack()
    exception_list = exception_list[:-2]
    exception_list.extend(traceback.format_tb(sys.exc_info()[2]))
    exception_list.extend(
        traceback.format_exception_only(sys.exc_info()[0], sys.exc_info()[1]),
    )

    exception_str = 'Traceback (most recent call last):\n'
    exception_str += ''.join(exception_list)
    # Removing the last \n
    exception_str = exception_str[:-1]

    return exception_str
