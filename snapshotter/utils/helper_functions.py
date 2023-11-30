import asyncio
import sys
from functools import wraps

import web3.datastructures

from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import logger
from snapshotter.utils.models.message_models import EpochBase

# setup logging
logger = logger.bind(module='Powerloom|HelperFunctions')


def cleanup_proc_hub_children(fn):
    """
    A decorator that wraps a function and handles cleanup of any child processes
    spawned by the function in case of an exception.

    Args:
        fn (function): The function to be wrapped.

    Returns:
        function: The wrapped function.
    """
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            fn(self, *args, **kwargs)
            logger.info('Finished running process hub core...')
        except Exception as e:
            logger.opt(exception=True).error(
                'Received an exception on process hub core run(): {}',
                e,
            )
            # logger.error('Initiating kill children....')
            # # silently kill all children
            # procs = psutil.Process().children()
            # for p in procs:
            #     p.terminate()
            # gone, alive = psutil.wait_procs(procs, timeout=3)
            # for p in alive:
            #     logger.error(f'killing process: {p.name()}')
            #     p.kill()
            self._kill_all_children()
            logger.error('Finished waiting for all children...now can exit.')
        finally:
            logger.error('Finished waiting for all children...now can exit.')
            self._reporter_thread.join()
            sys.exit(0)
            # sys.exit(0)
    return wrapper


def acquire_threading_semaphore(fn):
    """
    A decorator function that acquires a threading semaphore before executing the decorated function and releases it after execution.

    Args:
        fn (function): The function to be decorated.

    Returns:
        function: The decorated function.
    """
    @wraps(fn)
    def semaphore_wrapper(*args, **kwargs):
        semaphore = kwargs['semaphore']

        logger.debug('Acquiring threading semaphore')
        semaphore.acquire()
        try:
            resp = fn(*args, **kwargs)
        except Exception:
            raise
        finally:
            semaphore.release()

        return resp

    return semaphore_wrapper


def preloading_entry_exit_logger(fn):
    """
    Decorator function to log entry and exit of preloading worker functions.

    Args:
        fn (Callable): The function to be decorated.

    Returns:
        Callable: The decorated function.
    """
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        epoch: EpochBase = kwargs['epoch']
        try:
            await fn(self, *args, **kwargs)
            logger.info('Finished running preloader {}...', self.__class__.__name__)
        except asyncio.CancelledError:
            self._logger.error('Cancelled preloader worker {} for epoch {}', self.__class__.__name__, epoch.epochId)
            raise asyncio.CancelledError
        except Exception as e:
            self._logger.opt(exception=settings.logs.trace_enabled).error(
                'Exception while running preloader worker {} for epoch {}, Error: {}',
                self.__class__.__name__,
                epoch.epochId,
                e,
            )
            raise e
    return wrapper


async def as_completed_async(futures):
    """
    A coroutine that iterates over given futures and yields their results as they complete.

    Args:
        futures (List[asyncio.Future]): A list of asyncio.Future objects.

    Yields:
        The result of each completed future as it completes.
    """
    loop = asyncio.get_event_loop()
    wrappers = []
    for fut in futures:
        assert isinstance(fut, asyncio.Future)  # we need Future or Task
        # Wrap the future in one that completes when the original does,
        # and whose result is the original future object.
        wrapper = loop.create_future()
        fut.add_done_callback(wrapper.set_result)
        wrappers.append(wrapper)

    for next_completed in asyncio.as_completed(wrappers):
        # awaiting next_completed will dereference the wrapper and get
        # the original future (which we know has completed), so we can
        # just yield that
        yield await next_completed


def attribute_dict_to_dict(dictToParse: web3.datastructures.AttributeDict):
    """
    Converts an AttributeDict object to a regular dictionary object.

    Args:
        dictToParse (web3.datastructures.AttributeDict): The AttributeDict object to be converted.

    Returns:
        dict: The converted dictionary object.
    """
    # convert any 'AttributeDict' type found to 'dict'
    parsedDict = dict(dictToParse)
    for key, val in parsedDict.items():
        if 'list' in str(type(val)):
            parsedDict[key] = [_parse_value(x) for x in val]
        else:
            parsedDict[key] = _parse_value(val)
    return parsedDict


def _parse_value(val):
    """
    Parses the given value and returns a string representation of it.
    If the value is a nested dictionary, it is converted to a regular dictionary.
    If the value is of type 'HexBytes', it is converted to a string.

    Args:
        val: The value to be parsed.

    Returns:
        A string representation of the given value.
    """
    # check for nested dict structures to iterate through
    if 'dict' in str(type(val)).lower():
        return attribute_dict_to_dict(val)
    # convert 'HexBytes' type to 'str'
    elif 'HexBytes' in str(type(val)):
        return val.hex()
    else:
        return val
