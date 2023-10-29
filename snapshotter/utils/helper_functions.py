import asyncio
import sys
from functools import wraps

import psutil
import web3.datastructures

from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import logger
from snapshotter.utils.models.message_models import EpochBase

# setup logging
logger = logger.bind(module='Powerloom|HelperFunctions')


def cleanup_proc_hub_children(fn):
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
    # convert any 'AttributeDict' type found to 'dict'
    parsedDict = dict(dictToParse)
    for key, val in parsedDict.items():
        if 'list' in str(type(val)):
            parsedDict[key] = [_parse_value(x) for x in val]
        else:
            parsedDict[key] = _parse_value(val)
    return parsedDict


def _parse_value(val):
    # check for nested dict structures to iterate through
    if 'dict' in str(type(val)).lower():
        return attribute_dict_to_dict(val)
    # convert 'HexBytes' type to 'str'
    elif 'HexBytes' in str(type(val)):
        return val.hex()
    else:
        return val
