from typing import TypeVar, Callable, Coroutine, Any
from functools import wraps

T = TypeVar('T')

def acquire_bounded_semaphore(fn: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
    """
    A decorator function that acquires a bounded semaphore before executing the decorated function and releases it
    after the function is executed. This decorator is intended to be used with async functions.

    Args:
        fn: The async function to be decorated.

    Returns:
        The decorated async function.
    """
    @wraps(fn)
    async def wrapped(self, *args, **kwargs) -> T:
        sem: asyncio.BoundedSemaphore | None = kwargs.get('semaphore', None)
        if sem:
            await sem.acquire()
        result: T = None
        try:
            result = await fn(self, *args, **kwargs)
        except Exception as e:
            logger.opt(exception=True).error('Error in asyncio semaphore acquisition decorator: {}', e)
        finally:
            if sem:
                sem.release()
            return result
    return wrapped
