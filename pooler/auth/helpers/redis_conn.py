import redis
from redis import asyncio as aioredis
from redis.asyncio.connection import ConnectionPool

from pooler.auth.conf import auth_settings


def construct_redis_url():
    if auth_settings.redis.password:
        return (
            f'redis://{auth_settings.redis.password}@{auth_settings.redis.host}:{auth_settings.redis.port}'
            f'/{auth_settings.redis.db}'
        )
    else:
        return f'redis://{auth_settings.redis.host}:{auth_settings.redis.port}/{auth_settings.redis.db}'

# ref https://github.com/redis/redis-py/issues/936


async def get_aioredis_pool(pool_size=200):
    pool = ConnectionPool.from_url(
        url=construct_redis_url(),
        retry_on_error=[redis.exceptions.ReadOnlyError],
        max_connections=pool_size,
    )

    return aioredis.Redis(connection_pool=pool)


class RedisPoolCache:
    def __init__(self, pool_size=500):
        self._aioredis_pool = None
        self._pool_size = pool_size

    async def populate(self):
        if not self._aioredis_pool:
            self._aioredis_pool: aioredis.Redis = await get_aioredis_pool(
                self._pool_size,
            )
