import sys

from loguru import logger

from pooler.settings.config import settings

# {extra} field can be used to pass extra parameters to the logger using .bind()
FORMAT = '{time:MMMM D, YYYY > HH:mm:ss!UTC} | {level} | {message}| {extra}'


def trace_enabled(_):
    return settings.logs.trace_enabled


logger.configure(
    handlers=[
        {'sink': sys.stdout, 'level': 'DEBUG', 'format': FORMAT},
        {'sink': sys.stderr, 'level': 'WARNING', 'format': FORMAT},
        {
            'sink': sys.stderr, 'level': 'ERROR', 'format': FORMAT,
            'backtrace': True, 'diagnose': True,
        },
        {
            'sink': sys.stdout, 'level': 'TRACE', 'format': FORMAT,
            'filter': trace_enabled, 'backtrace': True, 'diagnose': True,
        },
    ],
)

if settings.logs.write_to_files:
    logger.add('logs/debug.log', level='DEBUG', format=FORMAT, rotation='1 day')
    logger.add('logs/warning.log', level='WARNING', format=FORMAT, rotation='1 day')
    logger.add('logs/error.log', level='ERROR', format=FORMAT, backtrace=True, rotation='1 day')
    logger.add('logs/trace.log', level='TRACE', format=FORMAT, filter=trace_enabled, backtrace=True, rotation='1 day')
