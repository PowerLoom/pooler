import asyncio

import pydantic
from aio_pika import connect, Message, Channel, IncomingMessage, ExchangeType
from redis_conn import provide_async_redis_conn_insta
from functools import partial
from async_limits.strategies import AsyncFixedWindowRateLimiter
from async_limits.storage import AsyncRedisStorage
from async_limits import parse_many as limit_parse_many
from dynaconf import settings
from eth_utils import keccak
from redis_keys import eth_log_request_data_f
from message_models import ethLogRequestModel
from init_rabbitmq import init_rmq_exchange_queue_async
from proto_system_logging import config_logger_with_namespace
from tenacity import retry, RetryError, wait_fixed, stop_after_attempt, stop_after_delay, retry_if_result
from datetime import datetime, timedelta
import aioredis
import json
import aiohttp
import logging.config
import os
import logging.handlers
import time


#set logger scope
# logging.root.setLevel(logging.getLevelName(os.environ.get("LOG_LEVEL", "DEBUG")))
# logging.config.dictConfig(config_logger_with_namespace('PowerLoom|EthLogs|worker'))
log_entry_logger = logging.getLogger('PowerLoom|EthLogs|worker')
log_entry_logger.setLevel(logging.DEBUG)
log_entry_logger.handlers = [logging.handlers.SocketHandler(host=settings.get('LOGGING_SERVER.HOST','localhost'),
            port=settings.get('LOGGING_SERVER.PORT',logging.handlers.DEFAULT_TCP_LOGGING_PORT))]


#Initialize rate limits when program starts
GLOBAL_RPC_RATE_LIMIT_STR = settings.RPC.rate_limit
PARSED_LIMITS = limit_parse_many(GLOBAL_RPC_RATE_LIMIT_STR)


### RATE LIMITER LUA SCRIPTS
SCRIPT_CLEAR_KEYS = """
        local keys = redis.call('keys', KEYS[1])
        local res = 0
        for i=1,#keys,5000 do
            res = res + redis.call(
                'del', unpack(keys, i, math.min(i+4999, #keys))
            )
        end
        return res
        """

SCRIPT_INCR_EXPIRE = """
        local current
        current = redis.call("incrby",KEYS[1],ARGV[2])
        if tonumber(current) == tonumber(ARGV[2]) then
            redis.call("expire",KEYS[1],ARGV[1])
        end
        return current
    """

# args = [value, expiry]
SCRIPT_SET_EXPIRE = """
    local keyttl = redis.call('TTL', KEYS[1])
    local current
    current = redis.call('SET', KEYS[1], ARGV[1])
    if keyttl == -2 then
        redis.call('EXPIRE', KEYS[1], ARGV[2])
    elseif keyttl ~= -1 then
        redis.call('EXPIRE', KEYS[1], keyttl)
    end
    return current
"""
### END RATE LIMITER LUA SCRIPTS


# needs to be run only once
async def load_rate_limiter_scripts(redis_conn: aioredis.Redis):
    script_clear_keys_sha = await redis_conn.script_load(SCRIPT_CLEAR_KEYS)
    script_incr_expire = await redis_conn.script_load(SCRIPT_INCR_EXPIRE)
    LUA_SCRIPT_SHAS = {
        "script_incr_expire": script_incr_expire,
        "script_clear_keys": script_clear_keys_sha
    }
    return LUA_SCRIPT_SHAS
    # above computes to this. init can be run as a separate script and the following can be referenced through settings
    # LUA_SCRIPT_SHAS = {
    #         "script_incr_expire": "2d8b8198bdec1c5324d18231400bf990e010674f",
    #         "script_clear_keys": "73c9b8f504c33418c74f79a3ac7be749c54004f4"
    #     }
    

async def get_aiohttp_cache() -> aiohttp.ClientSession:
    basic_rpc_connector = aiohttp.TCPConnector(limit=settings['rlimit']['file_descriptors'])
    aiohttp_client_basic_rpc_session = aiohttp.ClientSession(connector=basic_rpc_connector)
    return aiohttp_client_basic_rpc_session


def get_event_sig(event_name: str):
    if event_name == "FPMMBuy":
        event_def = "FPMMBuy(address,uint256,uint256,uint256,uint256)"
    elif event_name == "FPMMSell":
        event_def = f"FPMMSell(address,uint256,uint256,uint256,uint256)"
    else:
        log_entry_logger.debug("Unknown event_name passed: " + event_name)
        return -1

    event_sig = '0x' + keccak(text=event_def).hex()
    return event_sig

@retry(reraise=True, wait=wait_fixed(1), stop=(stop_after_delay(settings.RPC.LOGS_QUERY.TIMEOUT) | stop_after_attempt(settings.RPC.LOGS_QUERY.RETRY)))
async def make_post_call_async(url: str, params: dict, session: aiohttp.ClientSession, tag: int, redis_conn: aioredis.Redis):
    try:
        redis_storage = AsyncRedisStorage(await load_rate_limiter_scripts(redis_conn), redis_conn)
        custom_limiter = AsyncFixedWindowRateLimiter(redis_storage)
        limit_incr_by = 1   # score to be incremented for each request
        app_id = settings.RPC.MATIC[0].split('/')[-1]  # future support for loadbalancing over multiple MaticVigil RPC appID
        key_bits = [app_id, 'eth_getLogs']  # TODO: add unique elements that can identify a request
        can_request = True
        rate_limit_exception = False
        retry_after = 1
        response = None
        for each_lim in PARSED_LIMITS:
            # window_stats = custom_limiter.get_window_stats(each_lim, key_bits)
            # local_app_cacher_logger.debug(window_stats)
            # rest_logger.debug('Limit %s expiry: %s', each_lim, each_lim.get_expiry())
            try:
                if await custom_limiter.hit(each_lim, limit_incr_by, *[key_bits]) is False:
                    window_stats = await custom_limiter.get_window_stats(each_lim, key_bits)
                    reset_in = 1 + window_stats[0]
                    # if you need information on back offs
                    retry_after = reset_in - int(time.time())
                    retry_after = (datetime.now() + timedelta(0,retry_after)).isoformat()
                    can_request = False
                    break  # make sure to break once false condition is hit
            except (
                    aioredis.exceptions.ConnectionError, aioredis.exceptions.ResponseError,
                    aioredis.exceptions.RedisError, Exception
            ) as e:
                # shit can happen while each limit check call hits Redis, handle appropriately
                log_entry_logger.debug('Bypassing rate limit check for appID because of Redis exception: ' + str({'appID': app_id, 'exception': e}))
        if can_request:
            message = f"## Making async post call with params: {params}"
            log_entry_logger.debug(message)
            response_status_code = None
            rpc_error = "unknown"
            #shifted timeout logic to tenacity
            async with session.post(url=url, json=params) as response_obj:
                response = await response_obj.read()
                response_status_code = response_obj.status
                if response_status_code == 200:
                    response = json.loads(response)
                else:
                    response = None
                    try:
                        rpc_error = json.dumps(json.loads(response))
                    except Exception:
                        pass

            if response_status_code == 200 and type(response) is dict:
                response.update({'tag': tag})
                return response
            else:
                msg = f"Failed to make rpc request, url: {url} | status_code: {response_status_code} | message: {rpc_error}"
                raise RPCException(request=params, response=response, underlying_exception=None,
                                extra_info={'msg': msg, 'tag': tag, "rate_limit_exception": rate_limit_exception})
        else:
            msg = f"exhausted_api_key_rate_limit"
            rate_limit_exception = True
            raise RPCException(request=params, response={}, underlying_exception=None,
                            extra_info={'msg': msg, 'tag': tag, "rate_limit_exception": rate_limit_exception, "retry_after": retry_after})
    except aiohttp.ClientResponseError as terr:
        msg = 'aiohttp error occurred while making async post call'    
        raise RPCException(request=params, response=response, underlying_exception=terr,
                           extra_info={'msg': msg, 'tag': tag, "rate_limit_exception": rate_limit_exception})
    except RPCException as r:
        raise r
    except Exception as e:
        print("error in make_post_call_async: ", e)
        raise RPCException(request=params, response=response, underlying_exception=e,
                           extra_info={'msg': str(e), 'tag': tag, "rate_limit_exception": rate_limit_exception})


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


async def eth_get_logs_async(
    contract_address: str,
    events: list,
    from_block: int, 
    to_block: int,
    requestId: str,
    session: aiohttp.ClientSession,
    redis_conn: aioredis.Redis
):
    """
        Function to get the logs for the given data
    """
    
    try:
        event_sigs = list(map(get_event_sig, events))
        log_entry_logger.debug('Fetching logs for event topic: %s' % event_sigs)
        if -1 in event_sigs:
            _bad_event_name = event_sigs[event_sigs.index(-1)]
            raise AssertionError(f"Unknown event_name passed: {_bad_event_name}")

        assert from_block < to_block, f"from_block:{from_block} should be less than to_block:{to_block}"
        query_range_batches = dict()
        idx = 1
        completed_status = dict()
        final_logs = list()
        err_obj = dict()
        for begin_block in range(from_block, to_block, settings.RPC.LOGS_QUERY.CHUNK):
            from_block_query = hex(begin_block)
            if to_block - begin_block < settings.RPC.LOGS_QUERY.CHUNK:
                to_block_query = hex(to_block)
            else:
                to_block_query = hex(begin_block + settings.RPC.LOGS_QUERY.CHUNK - 1)
            query_range_batches.update({idx: (from_block_query, to_block_query)})
            completed_status.update({idx: False})
            idx += 1
        query_range_tasks = dict()
        for each_query_range_idx in query_range_batches.keys():
            each_query_range = query_range_batches[each_query_range_idx]
            requestParams = {
                "fromBlock": each_query_range[0],
                "toBlock": each_query_range[1],
            }
            if(event_sigs != None):
                requestParams["topics"] = event_sigs
            if(contract_address != None):
                requestParams["address"] = contract_address
            
            rpc_json = {
                "jsonrpc": "2.0",
                "method": "eth_getLogs",
                "params": [
                    requestParams
                ],
                "id": 74
            }
            t = make_post_call_async(
                url=settings.RPC.MATIC[0],
                params=rpc_json,
                session=session,
                tag=each_query_range_idx,
                redis_conn=redis_conn
            )
            query_range_tasks.update({each_query_range_idx: t})

        log_entry_logger.debug("Total number of tasks generated: %s\n" % len(query_range_tasks))
        
        #we don't need a while loop as tenacity will handle all retry logic
        #await for all tasks 
        rets = await asyncio.gather(*query_range_tasks.values(), return_exceptions=True)
        failed_batches = list()
        errs = list()
        for result in rets:
            result_idx = 0
            err_obj = None
            if isinstance(result, RPCException) and result.extra_info["rate_limit_exception"]:
                result_idx = result.extra_info['tag']
                err_obj = {
                    'contract': contract_address,
                    'request': result.request,
                    'response': result.response,
                    'underlying_exception': result.underlying_exception,
                    'error': result.extra_info['msg'],
                    'retry_after': result.extra_info['retry_after'],
                    "requestId": requestId
                }
                # log_entry_logger.error("Error: %s\n", result.extra_info['msg'], exc_info=True)
            elif isinstance(result, RPCException):
                err_obj = {
                    'contract': contract_address,
                    'request': result.request,
                    'response': result.response,
                    'underlying_exception': result.underlying_exception,
                    'error': result.extra_info['msg'],
                    "requestId": requestId
                }
                result_idx = result.extra_info['tag']
                # log_entry_logger.error("## Error: %s || result_idx: %s\n" % (result.extra_info['msg'], result_idx), exc_info=True)
                failed_batches.append(err_obj)
            elif type(result) is dict:
                result_idx = result['tag']
                if 'result' not in result.keys() or type(result['result']) is not list:
                    err_obj = {
                        'contract': contract_address,
                        'request_query_range': query_range_batches.get(result_idx, None),
                        'response': result,
                        'error': "Failed to get logs",
                        "requestId": requestId 
                    }
                    # log_entry_logger.error("Failed to get logs | Returned result:\n%s" % str(err_obj), exc_info=True)
                else:
                    final_logs.extend(result['result'])
                    log_entry_logger.debug('Fetched logs range: %s' % str(query_range_batches.get(result_idx, None)))
            else:
                err_obj = {
                    'contract': contract_address,
                    'request_query_range': query_range_batches.get(result_idx, None),
                    'response': result,
                    'error': "unknown error",
                    "requestId": requestId
                }
                # log_entry_logger.error("Failed to get logs | Returned result:%s \n" % result, exc_info=True)
            if result_idx and err_obj:
                failed_batches.append(query_range_batches[result_idx])
                log_entry_logger.error('Failed to get logs for range: %s', query_range_batches[result_idx])
                errs.append(err_obj)
        if errs:
            return final_logs, errs
        else:
            return final_logs, None

    except AssertionError as msg:
        log_entry_logger.error("Final AssertionError cached: %s" % msg, exc_info=True)
        return None, { 'error': str(msg), 'contract': contract_address, "requestId": requestId}
    except Exception as err:
        log_entry_logger.error("Final Error catched: %s" % str(err), exc_info=True)
        return None, { 'error': str(err), 'contract': contract_address, "requestId": requestId}


# TODO: remove dependency on singular redis conn supplier
@provide_async_redis_conn_insta
async def ethLogWorker(
    loop,
    redis_conn: aioredis.Redis = None
):   
    #init exchange and queue
    eth_logs_exchange, receiverQueue, senderQueue = await init_rmq_exchange_queue_async()

    async def requestMessageHandler(message: IncomingMessage):
        with message.process():
            request_body = json.loads(message.body)
            log_entry_logger.debug("Got a logs request: " + request_body.get('requestId'))
            asyncio.ensure_future(eth_log_worker(request_body))

    async def eth_log_worker(request_body):
        try:
            validated_request: ethLogRequestModel = ethLogRequestModel.parse_obj(request_body)
        except pydantic.ValidationError:
            return
        session = await get_aiohttp_cache()

        result, err_obj = await eth_get_logs_async(
            request_body.get('contract'),
            request_body.get('topics'),
            request_body.get('fromBlock'),
            request_body.get('toBlock'),
            request_body.get('requestId'),
            session,
            redis_conn
        )

        if err_obj:
            log_entry_logger.error("## There was 'errors' processing eth logs: %s" % err_obj)
        else:
            log_entry_logger.debug("## Processed Eth log, sending results of length: %2d" % len(result or []))


        # results
        request_body["logs"] = result
        request_body["error"] = err_obj

        # TODO: sender queue most likely not necessary
        # publish result on sender queue
        # await eth_logs_exchange.publish(
        #     Message(
        #         bytes(
        #             json.dumps(request_body),
        #             'utf-8'
        #         )
        #     ),
        #     routing_key=settings.ETH_LOG_WORKER.SENDER_QUEUE_NAME
        # )

        # update results on redis
        # do not modify polymarket specific trade volume/liquidity information here. Only set the results in cache/DB
        await redis_conn.set(eth_log_request_data_f.format(validated_request.requestId), json.dumps(request_body))
        log_entry_logger.debug("Completed fetching logs against request ID %s", validated_request.requestId)

    # Start listening the random queue
    await receiverQueue.consume(requestMessageHandler)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(ethLogWorker(loop))
    log_entry_logger.debug(" [*] Waiting for messages. To exit press CTRL+C")
    print(" [*] Waiting for messages. To exit press CTRL+C")
    loop.run_forever()
