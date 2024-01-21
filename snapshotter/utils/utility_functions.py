import asyncio
import datetime
from functools import wraps
import sys

from redis import asyncio as aioredis
from requests import Response

from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import logger
from snapshotter.utils.exceptions import RPCException
from snapshotter.utils.redis.redis_keys import active_status_key
from snapshotter.utils.redis.redis_keys import time_to_resume_active_status_key


def acquire_bounded_semaphore(fn):
    """
    A decorator function that acquires a bounded semaphore before executing the decorated function and releases it
    after the function is executed. This decorator is intended to be used with async functions.

    Args:
        fn: The async function to be decorated.

    Returns:
        The decorated async function.
    """
    @wraps(fn)
    async def wrapped(self, *args, **kwargs):
        sem: asyncio.BoundedSemaphore = kwargs['semaphore']
        await sem.acquire()
        result = None
        try:
            print('acquired semaphore') 
            result = await fn(self, *args, **kwargs)
        except Exception as e:
            logger.opt(exception=True).error('Error in asyncio semaphore acquisition decorator: {}', e)
        else:
            if result.status_code == 429:
                print('tiger')
                result_data = result.json()

                error_data = result_data.get('error', {}).get('data', {}).get('rate', {})

                if 'daily request count exceeded' in result_data.get('error', {}).get('message', ''):
                    print('deactivate')
                    redis_conn = kwargs.get('redis_conn', None)
                    if redis_conn is None:
                        for arg in args:
                            if isinstance(arg, aioredis.Redis):
                                redis_conn = arg
                                break
                    if redis_conn is not None:
                        # get current active status
                        active_status = await redis_conn.get(active_status_key)
                        # if active status is already False, then do nothing
                        if active_status is not None and int(active_status) == int(False):
                            self._logger.warning('Daily request count exceeded, deactivating for the day')
                            # set the active status key to False
                            await redis_conn.set(active_status_key, int(False))
                            # set time to resume active status to 24 hours from now
                            seconds_to_resume = int(datetime.datetime.now().timestamp()) + 24 * 60 * 60
                            await redis_conn.set(time_to_resume_active_status_key, seconds_to_resume)
                    else:
                        self._logger.warning('Redis connection not found, cannot deactivate')

                if error_data.get('backoff_seconds', None) is not None:
                    print('liger')
                    self._logger.warning(
                        'Rate limit exceeded, sleeping for {} seconds',
                        error_data['backoff_seconds'],
                    )
                    await asyncio.sleep(error_data['backoff_seconds'])

                    # return await fn(self, *args, **kwargs)  # retry
                    return {'data': bytes(0)}

                

        finally:
            sem.release()
            return result
    return wrapped
