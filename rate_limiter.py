from typing import List
from redis import asyncio as aioredis
from async_limits.strategies import AsyncFixedWindowRateLimiter
from async_limits.storage import AsyncRedisStorage
from async_limits import RateLimitItem
from rpc_helper import RPCException
import redis.exceptions
import time


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


async def generic_rate_limiter(
        parsed_limits: List[RateLimitItem],
        key_bits: list,
        redis_conn: aioredis.Redis,
        rate_limit_lua_script_shas=None,
        limit_incr_by=1
):
    """
    return: tuple of (can_request, retry_after in case of false can_request, violated rate limit string if applicable)
    """
    if not rate_limit_lua_script_shas:
        rate_limit_lua_script_shas = await load_rate_limiter_scripts(redis_conn)
    redis_storage = AsyncRedisStorage(rate_limit_lua_script_shas, redis_conn)
    custom_limiter = AsyncFixedWindowRateLimiter(redis_storage)
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
                return False, retry_after, str(each_lim)
        except (
                redis.exceptions.ConnectionError, redis.exceptions.TimeoutError,
                redis.exceptions.ResponseError
        ) as exc:
            raise Exception from exc
    return True, 0, ''


async def check_rpc_rate_limit(
        parsed_limits: list,
        app_id,
        redis_conn: aioredis.Redis,
        request_payload,
        error_msg,
        logger,
        rate_limit_lua_script_shas=None,
        limit_incr_by=1
):
    """
        rate limiter for rpc calls
    """
    key_bits = [app_id, 'eth_call']  # TODO: add unique elements that can identify a request
    try:
        can_request, retry_after, violated_limit = await generic_rate_limiter(
            parsed_limits,
            key_bits,
            redis_conn,
            rate_limit_lua_script_shas
        )
    except Exception as exc:
        logger.error(
            'Caught exception on rate limiter operations: %s | Bypassing rate limit check ', exc, exc_info=True
        )
        raise

    if not can_request:
        raise RPCException(
            request=request_payload,
            response={}, underlying_exception=None,
            extra_info=error_msg
        )
    return can_request
