import logging.config
from dynaconf import settings


###### Init Logger #####
logger = logging.getLogger('PowerLoom|UniswapHelpers')
logger.setLevel(logging.DEBUG)
logger.handlers = [logging.handlers.SocketHandler(host=settings.get('LOGGING_SERVER.HOST','localhost'), 
    port=settings.get('LOGGING_SERVER.PORT',logging.handlers.DEFAULT_TCP_LOGGING_PORT))]
########################