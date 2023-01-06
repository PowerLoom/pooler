import sys

from loguru import logger

# {extra} field can be used to pass extra parameters to the logger using .bind()
FORMAT = '{time:MMMM D, YYYY > HH:mm:ss!UTC} | {level} | {message}| {extra}'

logger.remove(0)
logger.add(sys.stdout, level='DEBUG', format=FORMAT)
logger.add(sys.stderr, level='WARNING', format=FORMAT)
logger.add(sys.stderr, level='ERROR', format=FORMAT)
