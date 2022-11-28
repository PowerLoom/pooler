import time
from datetime import datetime, timedelta

from redis import asyncio as aioredis
import redis.exceptions
from async_limits.strategies import AsyncFixedWindowRateLimiter
from async_limits.storage import AsyncRedisStorage
from rpc_helper import RPCException


# Initialize rate limits when program starts
LUA_SCRIPT_SHAS = None

# # # RATE LIMITER LUA SCRIPTS
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


# # # END RATE LIMITER LUA SCRIPTS

# needs to be run only once
async def load_rate_limiter_scripts(redis_conn: aioredis.Redis):
    script_clear_keys_sha = await redis_conn.script_load(SCRIPT_CLEAR_KEYS)
    script_incr_expire = await redis_conn.script_load(SCRIPT_INCR_EXPIRE)
    return {
        "script_incr_expire": script_incr_expire,
        "script_clear_keys": script_clear_keys_sha
    }



async def check_rpc_rate_limit(parsed_limits: list, app_id, redis_conn: aioredis.Redis, request_payload, error_msg, logger, rate_limit_lua_script_shas=None, limit_incr_by=1):
    """
        rate limiter for rpc calls
    """
    if not rate_limit_lua_script_shas:
        rate_limit_lua_script_shas = await load_rate_limiter_scripts(redis_conn)
    redis_storage = AsyncRedisStorage(rate_limit_lua_script_shas, redis_conn)
    custom_limiter = AsyncFixedWindowRateLimiter(redis_storage)
    key_bits = [app_id, 'eth_call']  # TODO: add unique elements that can identify a request
    can_request = False
    retry_after = 1
    for each_lim in parsed_limits:
        # window_stats = custom_limiter.get_window_stats(each_lim, key_bits)
        # local_app_cacher_logger.debug(window_stats)
        # rest_logger.debug('Limit %s expiry: %s', each_lim, each_lim.get_expiry())
        # async limits rate limit check
        # if rate limit checks out then we call
        try:
            if await custom_limiter.hit(each_lim, limit_incr_by, *[key_bits]) is False:
                window_stats = await custom_limiter.get_window_stats(each_lim, key_bits)
                reset_in = 1 + window_stats[0]
                # if you need information on back offs
                retry_after = reset_in - int(time.time())
                retry_after = (datetime.now() + timedelta(0, retry_after)).isoformat()
                can_request = False
                break  # make sure to break once false condition is hit
        except (
                redis.exceptions.ConnectionError, redis.exceptions.TimeoutError,
                redis.exceptions.ResponseError
        ) as exc:
            # shit can happen while each limit check call hits Redis, handle appropriately
            logger.debug('Bypassing rate limit check for appID because of Redis exception: ' + str(
                {'appID': app_id, 'exception': exc}))
            raise
        except Exception as exc:
            logger.error('Caught exception on rate limiter operations: %s', exc, exc_info=True)
            raise
        else:
            can_request = True

    if not can_request:
        raise RPCException(
            request=request_payload,
            response={}, underlying_exception=None,
            extra_info=error_msg
        )
    return can_request