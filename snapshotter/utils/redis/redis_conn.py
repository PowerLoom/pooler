import contextlib
from datetime import datetime
from functools import wraps
from pydoc import cli

import redis
import redis.exceptions as redis_exc
import tenacity
from redis import asyncio as aioredis
from redis.asyncio.connection import ConnectionPool

from snapshotter.settings.config import settings
from snapshotter.settings.config import settings as settings_conf
from snapshotter.utils.callback_helpers import send_failure_notifications_async
from snapshotter.utils.callback_helpers import send_failure_notifications_sync
from snapshotter.utils.default_logger import logger
from snapshotter.utils.models.data_models import SnapshotterIssue
from snapshotter.utils.models.data_models import SnapshotterReportState

# setup logging
logger = logger.bind(module='Powerloom|RedisConn')

REDIS_CONN_CONF = {
    'host': settings_conf.redis.host,
    'port': settings_conf.redis.port,
    'password': settings_conf.redis.password,
    'db': settings_conf.redis.db,
    'retry_on_error': [redis.exceptions.ReadOnlyError],
}


def construct_redis_url():
    """
    Constructs a Redis URL based on the REDIS_CONN_CONF dictionary.

    Returns:
        str: Redis URL constructed from REDIS_CONN_CONF dictionary.
    """
    if REDIS_CONN_CONF['password']:
        return (
            f'redis://{REDIS_CONN_CONF["password"]}@{REDIS_CONN_CONF["host"]}:{REDIS_CONN_CONF["port"]}'
            f'/{REDIS_CONN_CONF["db"]}'
        )
    else:
        return f'redis://{REDIS_CONN_CONF["host"]}:{REDIS_CONN_CONF["port"]}/{REDIS_CONN_CONF["db"]}'

# ref https://github.com/redis/redis-py/issues/936


async def get_aioredis_pool(pool_size=200):
    """
    Returns an aioredis Redis connection pool.

    Args:
        pool_size (int): Maximum number of connections to the Redis server.

    Returns:
        aioredis.Redis: Redis connection pool.
    """
    pool = ConnectionPool.from_url(
        url=construct_redis_url(),
        retry_on_error=[redis.exceptions.ReadOnlyError],
        max_connections=pool_size,
    )

    return aioredis.Redis(connection_pool=pool)


@contextlib.contextmanager
def create_redis_conn(
    connection_pool: redis.BlockingConnectionPool,
) -> redis.Redis:
    """
    Context manager for creating a Redis connection using a connection pool.

    Args:
        connection_pool (redis.BlockingConnectionPool): The connection pool to use.

    Yields:
        redis.Redis: A Redis connection object.

    Raises:
        redis_exc.RedisError: If there is an error connecting to Redis.
    """
    try:
        redis_conn = redis.Redis(connection_pool=connection_pool)
        yield redis_conn
    except redis_exc.RedisError:
        raise
    except KeyboardInterrupt:
        pass


@tenacity.retry(
    stop=tenacity.stop_after_delay(60),
    wait=tenacity.wait_random_exponential(multiplier=1, max=60),
    retry=tenacity.retry_if_exception_type(redis_exc.RedisError),
    reraise=True,
)
def provide_redis_conn(fn):
    """
    Decorator function that provides a Redis connection object to the decorated function.
    If the decorated function already has a Redis connection object in its arguments or keyword arguments,
    it will be used. Otherwise, a new connection object will be created and passed to the function.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        arg_conn = 'redis_conn'
        func_params = fn.__code__.co_varnames
        conn_in_args = arg_conn in func_params and func_params.index(
            arg_conn,
        ) < len(args)
        conn_in_kwargs = arg_conn in kwargs
        if conn_in_args or conn_in_kwargs:
            return fn(*args, **kwargs)
        else:
            connection_pool = redis.BlockingConnectionPool(**REDIS_CONN_CONF)

            with create_redis_conn(connection_pool) as redis_obj:
                kwargs[arg_conn] = redis_obj
                logger.debug(
                    'Returning after populating redis connection object',
                )
                return fn(*args, **kwargs)

    return wrapper


def provide_redis_conn_repsawning_thread(fn):
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        arg_conn = 'redis_conn'
        func_params = fn.__code__.co_varnames
        conn_in_args = arg_conn in func_params and func_params.index(
            arg_conn,
        ) < len(args)
        conn_in_kwargs = arg_conn in kwargs
        if conn_in_args or conn_in_kwargs:
            return fn(*args, **kwargs)
        else:
            connection_pool = redis.BlockingConnectionPool(**REDIS_CONN_CONF)
            while True:
                try:
                    with create_redis_conn(connection_pool) as redis_obj:
                        kwargs[arg_conn] = redis_obj
                        logger.debug(
                            'Returning after populating redis connection object',
                        )
                        _ = fn(self, *args, **kwargs)
                except Exception as e:
                    logger.opt(exception=True).error(e)
                    send_failure_notifications_sync(
                        client=self._httpx_client,
                        message=SnapshotterIssue(
                            instanceID=settings.instance_id,
                            issueType=SnapshotterReportState.CRASHED_REPORTER_THREAD.value,
                            projectID='',
                            epochId='',
                            timeOfReporting=datetime.now().isoformat(),
                            extra=str(e),
                        ),
                    )
                    continue
                # if no exception was caught and the thread returns normally, it is the sign of a shutdown event being set
                else:
                    return _

    return wrapper


def provide_async_redis_conn(fn):
    """
    Decorator function that provides an async Redis connection to the decorated function.

    Args:
        fn: The function to be decorated.

    Returns:
        The decorated function.
    """
    @wraps(fn)
    async def async_redis_conn_wrapper(*args, **kwargs):
        redis_conn_raw = await kwargs['request'].app.redis_pool.acquire()
        redis_conn = aioredis.Redis(redis_conn_raw)
        kwargs['redis_conn'] = redis_conn
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            logger.opt(exception=True).error(e)
            return {'error': 'Internal Server Error'}
        finally:
            kwargs['request'].app.redis_pool.release(redis_conn_raw)

    return async_redis_conn_wrapper


def provide_async_redis_conn_insta(fn):
    """
    A decorator function that provides an async Redis connection instance to the decorated function.

    Args:
        fn: The function to be decorated.

    Returns:
        The decorated function with an async Redis connection instance.

    """
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        arg_conn = 'redis_conn'
        if kwargs.get(arg_conn):
            return await fn(*args, **kwargs)
        else:
            redis_cluster_mode_conn = False
            # try:
            #     if settings_conf.redis.cluster_mode:
            #         redis_cluster_mode_conn = True
            # except:
            #     pass
            if redis_cluster_mode_conn:
                # connection = await aioredis_cluster.create_redis_cluster(
                #     startup_nodes=[(REDIS_CONN_CONF['host'], REDIS_CONN_CONF['port'])],
                #     password=REDIS_CONN_CONF['password'],
                #     pool_maxsize=1,
                #     ssl=REDIS_CONN_CONF['ssl']
                # )
                pass
            else:
                # logging.debug('Creating single connection via high level aioredis interface')
                connection = await aioredis.Redis(
                    host=REDIS_CONN_CONF['host'],
                    port=REDIS_CONN_CONF['port'],
                    db=REDIS_CONN_CONF['db'],
                    password=REDIS_CONN_CONF['password'],
                    retry_on_error=[redis.exceptions.ReadOnlyError],
                )
            kwargs[arg_conn] = connection
            try:
                return await fn(*args, **kwargs)
            except Exception:
                raise
            finally:
                try:  # ignore residual errors
                    await connection.close()
                except:
                    pass

    return wrapped


class RedisPoolCache:
    def __init__(self, pool_size=2000):
        """
        Initializes a Redis connection object with the specified connection pool size.

        Args:
            pool_size (int): The maximum number of connections to keep in the pool.
        """
        self._aioredis_pool = None
        self._pool_size = pool_size

    async def populate(self):
        """
        Populates the Redis connection pool with the specified number of connections.
        """
        if not self._aioredis_pool:
            self._aioredis_pool: aioredis.Redis = await get_aioredis_pool(
                self._pool_size,
            )
