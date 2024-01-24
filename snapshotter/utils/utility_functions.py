import asyncio
import typing as t
from functools import wraps

from snapshotter.utils.default_logger import logger


def acquire_bounded_semaphore(*dargs, **dkw):
    """
    A decorator factory that creates a decorator. This decorator acquires a bounded semaphore before executing 
    the decorated function and releases it after the function is executed. This decorator is intended to be 
    used with async functions.

    Supports both @acquire_bounded_semaphore and @acquire_bounded_semaphore(semaphore=your_semaphore) syntaxes.

    :param dargs: positional arguments, if a callable is detected, treat it as the decorated function.
    :param dkw: keyword arguments, expected to contain 'semaphore' for semaphore.
    """

    if len(dargs) == 1 and callable(dargs[0]) and not dkw:
        # When used as @acquire_bounded_semaphore without arguments
        fn = dargs[0]
        semaphore = asyncio.BoundedSemaphore()

        return acquire_bounded_semaphore(semaphore)(fn)

    else:
        # When used as @acquire_bounded_semaphore(semaphore=your_semaphore)
        semaphore = dkw.get('semaphore', asyncio.BoundedSemaphore())

        def decorator(fn):
            @wraps(fn)
            async def wrapped(*args, **kwargs):
                await semaphore.acquire()
                result = None
                try:
                    print('semaphore acquired')
                    print(semaphore)
                    result = await fn(*args, **kwargs)
                    print(result)
                except Exception as e:
                    print(e)
                    logger.opt(exception=True).error('Error in asyncio semaphore acquisition decorator: {}', e)
                finally:
                    semaphore.release()
                    return result
            return wrapped

        return decorator


# Example usage:
