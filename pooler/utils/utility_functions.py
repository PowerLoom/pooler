import asyncio
from functools import wraps
from math import floor
from pooler.utils.default_logger import logger


def acquire_bounded_semaphore(fn):
    @wraps(fn)
    async def wrapped(self, *args, **kwargs):
        sem: asyncio.BoundedSemaphore = kwargs['semaphore'] if 'semaphore' in kwargs else args[3]
        await sem.acquire()
        result = None
        try:
            result = await fn(self, *args, **kwargs)
        except Exception as e:
            logger.opt(exception=True).error('Error in asyncio semaphore acquisition decorator: {}', e)
        finally:
            sem.release()
            return result
    return wrapped

