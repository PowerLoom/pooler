import json
import sys
from functools import wraps

import aiohttp
import httpx

from pooler.settings.config import settings
from pooler.utils.default_logger import format_exception
from pooler.utils.default_logger import logger

# setup logging
logger = logger.bind(module='PowerLoom|HelperFunctions')


def make_post_call(url: str, params: dict):
    try:
        logger.debug('Making post call to {}: {}', url, params)
        response = httpx.post(url=url, json=params)
        if response.status_code == 200:
            return response.json()
        else:
            msg = (
                f'Failed to make request {params}. Got status response from'
                f' {url}: {response.status_code}'
            )
            return None
    except (
        httpx.TimeoutException,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.RequestError,
        httpx.ConnectError,
    ) as terr:
        logger.debug('Error occurred while making the post call.')
        logger.opt(exception=True, lazy=True).error(
            'Error {err}', err=lambda: format_exception(terr),
        )
        return None


class RPCException(Exception):
    def __init__(self, request, response, underlying_exception, extra_info):
        self.request = request
        self.response = response
        self.underlying_exception: Exception = underlying_exception
        self.extra_info = extra_info

    def __str__(self):
        ret = {
            'request': self.request,
            'response': self.response,
            'extra_info': self.extra_info,
            'exception': None,
        }
        if isinstance(self.underlying_exception, Exception):
            ret.update({'exception': self.underlying_exception.__str__()})
        return json.dumps(ret)

    def __repr__(self):
        return self.__str__()


# TODO: support basic failover and/or load balanced calls that use the list of URLs. Introduce in rpc_helper.py
async def make_post_call_async(
    url: str, params: dict, session: aiohttp.ClientSession, tag: int,
):
    try:
        message = f'Making async post call to {url}: {params}'
        logger.debug(message)
        response_status_code = None
        response = None
        # per request timeout instead of configuring a client session wide timeout
        # from reported issue https://github.com/aio-libs/aiohttp/issues/3203
        async with session.post(
            url=url,
            json=params,
            timeout=aiohttp.ClientTimeout(
                total=None,
                sock_read=settings.timeouts.archival,
                sock_connect=settings.timeouts.connection_init,
            ),
        ) as response_obj:
            response = await response_obj.json()
            response_status_code = response_obj.status
        if response_status_code == 200 and type(response) is dict:
            response.update({'tag': tag})
            return response
        else:
            msg = (
                f'Failed to make request {params}. Got status response from'
                f' {url}: {response_status_code}'
            )
            logger.trace(msg)

            exc = RPCException(
                request=params,
                response=response,
                underlying_exception=None,
                extra_info={'msg': msg, 'tag': tag},
            )
            logger.opt(exception=True).trace('Error {}', str(exc))
            raise exc

    except aiohttp.ClientResponseError as terr:
        msg = 'aiohttp error occurred while making async post call'
        logger.opt(exception=True, lazy=True).trace(
            'Error {err}', err=lambda: format_exception(terr),
        )
        raise RPCException(
            request=params,
            response=response,
            underlying_exception=terr,
            extra_info={'msg': msg, 'tag': tag},
        )
    except Exception as e:
        msg = 'Exception occurred while making async post call'
        logger.opt(exception=True, lazy=True).trace(
            'Error {err}', err=lambda: format_exception(e),
        )
        raise RPCException(
            request=params,
            response=response,
            underlying_exception=e,
            extra_info={'msg': msg, 'tag': tag},
        )


def cleanup_children_procs(fn):
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
            logger.error('Waiting on spawned callback workers to join...')
            for (
                worker_class_name,
                unique_worker_entries,
            ) in self._spawned_cb_processes_map.items():
                for (
                    worker_unique_id,
                    worker_unique_process_details,
                ) in unique_worker_entries.items():
                    if worker_unique_process_details['process'].pid:
                        logger.error(
                            (
                                'Waiting on spawned callback worker {} | Unique'
                                ' ID {} | PID {}  to join...'
                            ),
                            worker_class_name,
                            worker_unique_id,
                            worker_unique_process_details['process'].pid,
                        )
                        worker_unique_process_details['process'].join()

            logger.error(
                'Waiting on spawned core workers to join... {}',
                self._spawned_processes_map,
            )
            for (
                worker_class_name,
                unique_worker_entries,
            ) in self._spawned_processes_map.items():
                logger.error(
                    'spawned Process Pid to wait on {}',
                    unique_worker_entries.pid,
                )
                # internal state reporter might set proc_id_map[k] = -1
                if unique_worker_entries != -1:
                    logger.error(
                        (
                            'Waiting on spawned core worker {} | PID {}  to'
                            ' join...'
                        ),
                        worker_class_name,
                        unique_worker_entries.pid,
                    )
                    unique_worker_entries.join()
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


# # # END: placeholder for supporting liquidity events
