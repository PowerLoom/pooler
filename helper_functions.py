from web3 import Web3, WebsocketProvider, HTTPProvider
from exceptions import SelfExitException
from cached_property import cached_property as cached_property_async
from typing import Union
from eth_account.messages import encode_defunct
from eth_account.account import Account
from eth_utils import keccak
from functools import wraps, reduce
from dynaconf import settings
from redis_conn import provide_redis_conn, provide_redis_conn_insta, provide_async_redis_conn_insta, REDIS_CONN_CONF
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception, RetryCallState
from proto_system_logging import config_logger_with_namespace
from uuid import uuid4
import redis
import psutil
import os
import aioredis
import asyncio
import aiohttp
import logging
import logging.handlers
import sys
import eth_abi
import json
import time
import requests

""" Initialize the loggers """
# logging = logging.getLogger('PowerLoom|Helpers')
# logging.addHandler(logging.handlers.SocketHandler(**{
#     'host': 'localhost', 'port': logging.handlers.DEFAULT_TCP_LOGGING_PORT
# }))
# logging.setLevel(logging.DEBUG)
# logging.debug('Got powerloom helpers library logger')


def construct_kazoo_url(
        user=settings.ZOOKEEPER['user'],
        password=settings.ZOOKEEPER['password'],
        host=settings.ZOOKEEPER['host'],
        port=settings.ZOOKEEPER['port']
):
    if user and password:
        seg_1 = f'{user}:{password}@'
    else:
        seg_1 = ''
    if host and port:
        seg_2 = f'{host}:{port}'
    else:
        seg_2 = '127.0.0.1:2181'
    return f'{seg_1}{seg_2}'


class FailedRequestToMaticVigil(Exception):
    pass


class AsyncHTTPSessionCache:
    @cached_property_async
    async def get_aiohttp_cache(self) -> aiohttp.ClientSession:
        basic_rpc_connector = aiohttp.TCPConnector(limit=settings['rlimit']['file_descriptors'])
        aiohttp_client_basic_rpc_session = aiohttp.ClientSession(
            connector=basic_rpc_connector
        )
        return aiohttp_client_basic_rpc_session


def make_post_call(url: str, params: dict):
    try:
        logging.debug('Making post call to %s: %s', url, params)
        response = requests.post(url, json=params)
        if response.status_code == 200:
            return response.json()
        else:
            msg = f"Failed to make request {params}. Got status response from {url}: {response.status_code}"
            return None
    except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError
    ) as terr:
        logging.debug("Error occurred while making the post call.")
        logging.error(terr, exc_info=True)
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
            'exception': None
        }
        if isinstance(self.underlying_exception, Exception):
            ret.update({'exception': self.underlying_exception.__str__()})
        return json.dumps(ret)

    def __repr__(self):
        return self.__str__()


# TODO: support basic failover and/or load balanced calls that use the list of URLs. Introduce in rpc_helper.py
async def make_post_call_async(url: str, params: dict, session: aiohttp.ClientSession, tag: int):
    try:
        message = f"Making async post call to {url}: {params}"
        logging.debug(message)
        response_status_code = None
        response = None
        # per request timeout instead of configuring a client session wide timeout
        # from reported issue https://github.com/aio-libs/aiohttp/issues/3203
        async with session.post(url=url, json=params, timeout=aiohttp.ClientTimeout(
                total=None,
                sock_read=settings.TIMEOUTS.ARCHIVAL,
                sock_connect=settings.TIMEOUTS.CONNECTION_INIT
        )) as response_obj:
            response = await response_obj.json()
            response_status_code = response_obj.status
        if response_status_code == 200 and type(response) is dict:
            response.update({'tag': tag})
            return response
        else:
            msg = f"Failed to make request {params}. Got status response from {url}: {response_status_code}"
            logging.error(msg)
            raise RPCException(request=params, response=response, underlying_exception=None,
                               extra_info={'msg': msg, 'tag': tag})
    except aiohttp.ClientResponseError as terr:
        msg = 'aiohttp error occurred while making async post call'
        logging.debug(msg)
        logging.error(terr, exc_info=True)
        raise RPCException(request=params, response=response, underlying_exception=terr,
                           extra_info={'msg': msg, 'tag': tag})
    except Exception as e:
        msg = 'Exception occurred while making async post call'
        logging.debug(msg)
        logging.error(e, exc_info=True)
        raise RPCException(request=params, response=response, underlying_exception=e,
                           extra_info={'msg': msg, 'tag': tag})


def cleanup_children_procs(fn):
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            fn(self, *args, **kwargs)
        except (SelfExitException, Exception) as e:
            if not isinstance(e, SelfExitException):
                logging.error(e, exc_info=True)
            logging.error('Initiating kill children....')
            # silently kill all children
            procs = psutil.Process().children()
            for p in procs:
                p.terminate()
            gone, alive = psutil.wait_procs(procs, timeout=3)
            for p in alive:
                logging.error(f'killing process: {p.name()}')
                p.kill()
                if hasattr(self, '_spawned_cb_processes_map'):
                    for k, v in self._spawned_cb_processes_map.items():
                        if v['process'].pid == p.pid:
                            v['process'].join()
                if hasattr(self, '_spawned_processes_map'):
                    for k, v in self._spawned_processes_map.items():
                        # internal state reporter might set proc_id_map[k] = -1 
                        if v != -1 and v.pid == p.pid:
                            v.join()
            logging.error('Killed all child processes')
            
            current_process_pid = os.getpid()
            p = psutil.Process(current_process_pid)
            logging.error(f"Current process name: {p.name()} | pid: {current_process_pid}")
            logging.error('Attempting to send SIGTERM to process ID %s for following command', current_process_pid)
            p.terminate() 
            logging.error('Waiting for 3 seconds to confirm termination of process')
            gone, alive = psutil.wait_procs([p], timeout=3)
            for p_ in alive:
                logging.error('Process ID %s not terminated by SIGTERM. Sending SIGKILL...', p_.pid)
                p_.kill()
        finally:
            return None

    return wrapper


def acquire_threading_semaphore(fn):
    @wraps(fn)
    def semaphore_wrapper(*args, **kwargs):
        semaphore = kwargs['semaphore']

        logging.debug("Acquiring threading semaphore")
        semaphore.acquire()
        try:
            resp = fn(*args, **kwargs)
        except Exception as e:
            raise
        finally:
            semaphore.release()

        return resp

    return semaphore_wrapper


@provide_redis_conn_insta
def acquire_maticivigil_rpc_semaphore(app_id=settings.RPC.MATIC[0].split('/')[-1], redis_conn: redis.Redis = None):
    p = redis_conn.pipeline()
    identifier = str(uuid4())
    now = time.time()
    semaphore_name = f'{app_id}:maticivigil:rpcSemaphore'
    logging.info('About to acquire RPC semaphore via zset %s', semaphore_name)
    # cleanout stagnant entries older than 60 seconds
    p.zremrangebyscore(semaphore_name, '-inf', now - 60)
    # logging.info('Removed old acquisition entries for RPC semaphore via zset %s', semaphore_name)
    p.zadd(semaphore_name, {identifier: now})
    # logging.info('Added new identifier for acquisition request %s in RPC semaphore via zset %s', identifier, semaphore_name)
    p.zrank(semaphore_name, identifier)
    # logging.info('Getting rank of new identifier %s for acquisition request in RPC semaphore via zset %s', identifier, semaphore_name)
    result = p.execute()
    logging.debug('Pipeline results in acquiring RPC semaphore via zset %s', result)
    if result[-1] < settings.SNAPSHOT_MAX_WORKERS:
        return identifier
    else:
        redis_conn.zrem(semaphore_name, identifier)
        return None


@provide_async_redis_conn_insta
async def acquire_maticivigil_rpc_semaphore_async(app_id=settings.RPC.MATIC[0].split('/')[-1],
                                                  redis_conn: aioredis.Redis = None):
    cmds_gather = list()
    # p = redis_conn.pipeline()
    identifier = str(uuid4())
    now = time.time()
    semaphore_name = f'{app_id}:maticivigil:rpcSemaphore'
    logging.info('About to acquire RPC semaphore via zset %s', semaphore_name)
    # cleanout stagnant entries older than 60 seconds
    cmds_gather.append(redis_conn.zremrangebyscore(key=semaphore_name, max=now - 60))
    cmds_gather.append(redis_conn.zadd(semaphore_name, now, identifier))
    cmds_gather.append(redis_conn.zrank(semaphore_name, identifier))
    # result = await p.execute()
    result = await asyncio.gather(*cmds_gather)
    logging.debug('Pipeline results in acquiring RPC semaphore via zset %s', result)
    if result[-1] < settings.SNAPSHOT_MAX_WORKERS:
        return identifier
    else:
        redis_conn.zrem(semaphore_name, identifier)
        return None


@provide_redis_conn_insta
def release_maticivigil_rpc_semaphore(identifier, app_id=settings.RPC.MATIC[0].split('/')[-1],
                                      redis_conn: redis.Redis = None):
    semaphore_name = f'{app_id}:maticivigil:rpcSemaphore'
    return redis_conn.zrem(semaphore_name, identifier)


@provide_async_redis_conn_insta
async def release_maticivigil_rpc_semaphore_async(identifier, app_id=settings.RPC.MATIC[0].split('/')[-1],
                                                  redis_conn: aioredis.Redis = None):
    semaphore_name = f'{app_id}:maticivigil:rpcSemaphore'
    return await redis_conn.zrem(semaphore_name, identifier)


# # # TODO: BEGIN: placeholder for supporting liquidity events

def get_event_name_from_sig(event_sig: str):
    if event_sig == get_event_sig("FPMMBuy"):
        return "FPMMBuy"
    elif event_sig == get_event_sig("FPMMSell"):
        return "FPMMSell"
    return -1


def get_event_params_from_sig(event_sig: str):
    indexed_params = {}
    unindexed_params = {}
    if event_sig == get_event_sig("FPMMBuy"):
        indexed_params = {
            'buyer': 'address',
            'outcomeIndex': 'uint256'
        }

        unindexed_params = {
            'investmentAmount': 'uint256',
            'feeAmount': 'uint256',
            'outcomeTokensBought': 'uint256'
        }
    elif event_sig == get_event_sig("FPMMSell"):
        indexed_params = {
            'seller': 'address',
            'outcomeIndex': 'uint256'
        }

        unindexed_params = {
            'returnAmount': 'uint256',
            'feeAmount': 'uint256',
            'outcomeTokensSold': 'uint256'
        }

    return indexed_params, unindexed_params


def get_event_sig(event_name: str):
    if event_name == "FPMMBuy":
        event_def = "FPMMBuy(address,uint256,uint256,uint256,uint256)"
    elif event_name == "FPMMSell":
        event_def = f"FPMMSell(address,uint256,uint256,uint256,uint256)"
    else:
        logging.debug("Unknow event_name passed: ")
        logging.debug(event_name)
        return -1

    event_sig = '0x' + keccak(text=event_def).hex()
    # logging.debug("Generated event sig: ")
    # logging.debug(event_sig)

    return event_sig


def decode_event_data(topics: list, data: str):
    """
        - Given the topic and data, decode the values and return back
        the parameters
    """
    assert len(topics) > 0, "Empty topic sent as a parameter"

    event_sig = topics[0]

    # Decode the indexed_params
    indexed_params, unindexed_params = get_event_params_from_sig(event_sig=event_sig)

    indexed_data = {}
    unindexed_data = {}

    for i in range(1, len(topics)):
        param_name = list(indexed_params.keys())[i - 1]
        indexed_data[param_name] = eth_abi.decode_single(
            typ=indexed_params[param_name],
            data=bytes.fromhex(topics[i][2:])
        )
    _data = eth_abi.decode_abi(
        types=unindexed_params.values(),
        data=bytes.fromhex(data[2:])
    )
    for i in range(len(_data)):
        param_name = list(unindexed_params.keys())[i]
        unindexed_data[param_name] = _data[i]

    final_data = {'event_sig': topics[0]}
    final_data.update(indexed_data)
    final_data.update(unindexed_data)

    return final_data


def parse_logs(result: list):
    """
        Given a list of logs, parse them
    """

    events = []
    for log in result:
        if 'topics' not in log.keys():
            logging.debug("Unknown log found. Skipping...")
            logging.debug(log)
            continue

        try:
            event_data = decode_event_data(
                topics=log['topics'],
                data=log['data']
            )
        except AssertionError as aerr:
            logging.debug("Empty topics log. Skipping...")
            logging.debug(log)
            continue

        block_num = int(log['blockNumber'], base=16)
        event_data['blockNumber'] = block_num
        events.append(event_data)

    return events

# # # END: placeholder for supporting liquidity events
