from typing import Optional, Union
from fastapi import Depends, FastAPI, Request, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from auth.redis_keys import (
    user_details_htable, all_users_set, user_active_api_keys_set, user_revoked_api_keys_set, api_key_to_owner_key
)
from urllib.parse import urlencode, urljoin
from dynaconf import settings
from auth.data_models import AppOwnerModel, AddApiKeyRequest, UserAllDetailsResponse
import logging
import sys
import coloredlogs
from redis import asyncio as aioredis
import time
from auth.redis_conn import RedisPoolCache


formatter = logging.Formatter(u"%(levelname)-8s %(name)-4s %(asctime)s,%(msecs)d %(module)s-%(funcName)s: %(message)s")

stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setLevel(logging.DEBUG)
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.ERROR)

api_logger = logging.getLogger(__name__)
api_logger.setLevel(logging.DEBUG)
api_logger.addHandler(stdout_handler)
api_logger.addHandler(stderr_handler)
coloredlogs.install(level='DEBUG', logger=api_logger, stream=sys.stdout)

# setup CORS origins stuff
origins = ["*"]
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.on_event('startup')
async def startup_boilerplate():
    app.state.aioredis_pool = RedisPoolCache(pool_size=100)
    await app.state.aioredis_pool.populate()
    app.state.redis_pool = app.state.aioredis_pool._aioredis_pool
    app.state.core_settings = settings


@app.post('/user')
async def create_update_user(
        request: Request,
        user_cu_request: AppOwnerModel,
        response: Response

):
    """
    can be used for both creating a new entity or updating an entity's information in the redis htable
    """
    redis_conn: aioredis.Redis = request.app.state.redis_pool
    try:
        await redis_conn.sadd(
            all_users_set(),
            user_cu_request.email
        )
        user_cu_request.next_reset_at = int(time.time()) + 86400
        user_details = user_cu_request.dict()
        # api_logger.debug('User details after popping email: %s', user_details)
        await redis_conn.hset(
            name=user_details_htable(user_cu_request.email),
            mapping=user_details
        )
    except Exception as e:
        api_logger.error('%s', e, exc_info=True)
        return {'success': False}
    else:
        return {'success': True}


@app.post('/user/{email}/api_key')
async def add_api_key(
        api_key_request: AddApiKeyRequest,
        email: str,
        request: Request,
        response: Response
):
    redis_conn: aioredis.Redis = request.app.state.redis_pool
    if not await redis_conn.sismember(all_users_set(), email):
        response.status_code = 400
        return {'success': False}

    async with redis_conn.pipeline(transaction=True) as p:
        await p.sadd(
            user_active_api_keys_set(email),
            api_key_request.api_key
        ).set(api_key_to_owner_key(api_key_request.api_key), email).execute()
    return {'success': True}


@app.delete('/user/{email}/api_key')
async def revoke_api_key(
        api_key_request: AddApiKeyRequest,
        email: str,
        request: Request,
        response: Response
):
    redis_conn: aioredis.Redis = request.app.state.redis_pool
    if not await redis_conn.sismember(all_users_set(), email):
        response.status_code = 401
        return {'success': False}
    if not await redis_conn.sismember(user_active_api_keys_set(email), api_key_request.api_key):
        response.status_code = 401
        return {'success': False}
    elif await redis_conn.sismember(user_revoked_api_keys_set(email), api_key_request.api_key):
        response.status_code = 401
    await redis_conn.smove(user_active_api_keys_set(email), user_revoked_api_keys_set(email), api_key_request.api_key)
    return {'success': True}


@app.get('/user/{email}')
async def get_user_details(
        request: Request,
        response: Response,
        email: str
):
    redis_conn: aioredis.Redis = request.app.state.redis_pool

    all_details = await redis_conn.hgetall(name=user_details_htable(email))
    if not all_details:
        response.status_code = 400
        return {'success': False}
    active_api_keys = await redis_conn.smembers(name=user_active_api_keys_set(email))
    revoked_api_keys = await redis_conn.smembers(name=user_revoked_api_keys_set(email))

    return {
        'success': True,
        'data':
            UserAllDetailsResponse(
                **{k.decode('utf-8'): v.decode('utf-8') for k, v in all_details.items()},
                active_api_keys=[x.decode('utf-8') for x in active_api_keys],
                revoked_api_keys=[x.decode('utf-8') for x in revoked_api_keys]
            ).dict()
    }


@app.get('/users')
async def get_all_users(
        request: Request,
        response: Response
):
    redis_conn: aioredis.Redis = request.app.state.redis_pool
    all_users = await redis_conn.smembers(all_users_set())
    return {
        'success': True,
        'data': [x.decode('utf-8') for x in all_users]
    }
