import time

from fastapi import FastAPI
from fastapi import Request
from fastapi import Response
from fastapi.middleware.cors import CORSMiddleware
from redis import asyncio as aioredis

from pooler.auth.helpers.data_models import AddApiKeyRequest
from pooler.auth.helpers.data_models import AppOwnerModel
from pooler.auth.helpers.data_models import UserAllDetailsResponse
from pooler.auth.helpers.redis_conn import RedisPoolCache
from pooler.auth.helpers.redis_keys import all_users_set
from pooler.auth.helpers.redis_keys import api_key_to_owner_key
from pooler.auth.helpers.redis_keys import user_active_api_keys_set
from pooler.auth.helpers.redis_keys import user_details_htable
from pooler.auth.helpers.redis_keys import user_revoked_api_keys_set
from pooler.settings.config import settings
from pooler.utils.default_logger import logger

# setup logging
api_logger = logger.bind(module=__name__)

# setup CORS origins stuff
origins = ['*']
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
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
        response: Response,

):
    """
    can be used for both creating a new entity or updating an entity's information in the redis htable
    """
    redis_conn: aioredis.Redis = request.app.state.redis_pool
    try:
        await redis_conn.sadd(
            all_users_set(),
            user_cu_request.email,
        )
        if not await redis_conn.sismember(all_users_set(), user_cu_request.email):
            user_cu_request.next_reset_at = int(time.time()) + 86400
        user_details = user_cu_request.dict()
        await redis_conn.hset(
            name=user_details_htable(user_cu_request.email),
            mapping=user_details,
        )
    except Exception as e:
        api_logger.opt(exception=True).error('{}', e)
        return {'success': False}
    else:
        return {'success': True}


@app.post('/user/{email}/api_key')
async def add_api_key(
        api_key_request: AddApiKeyRequest,
        email: str,
        request: Request,
        response: Response,
):
    redis_conn: aioredis.Redis = request.app.state.redis_pool
    if not await redis_conn.sismember(all_users_set(), email):
        return {'success': False, 'error': 'User does not exists'}

    async with redis_conn.pipeline(transaction=True) as p:
        await p.sadd(
            user_active_api_keys_set(email),
            api_key_request.api_key,
        ).set(api_key_to_owner_key(api_key_request.api_key), email).execute()
    return {'success': True}


@app.delete('/user/{email}/api_key')
async def revoke_api_key(
        api_key_request: AddApiKeyRequest,
        email: str,
        request: Request,
        response: Response,
):
    redis_conn: aioredis.Redis = request.app.state.redis_pool
    if not await redis_conn.sismember(all_users_set(), email):
        return {'success': False, 'error': 'User does not exists'}

    if not await redis_conn.sismember(user_active_api_keys_set(email), api_key_request.api_key):
        return {'success': False, 'error': 'API key not active'}
    elif await redis_conn.sismember(user_revoked_api_keys_set(email), api_key_request.api_key):
        return {'success': False, 'error': 'API key already revoked'}
    await redis_conn.smove(user_active_api_keys_set(email), user_revoked_api_keys_set(email), api_key_request.api_key)
    return {'success': True}


@app.get('/user/{email}')
async def get_user_details(
        request: Request,
        response: Response,
        email: str,
):
    redis_conn: aioredis.Redis = request.app.state.redis_pool

    all_details = await redis_conn.hgetall(name=user_details_htable(email))
    if not all_details:
        return {'success': False, 'error': 'User does not exists'}

    active_api_keys = await redis_conn.smembers(name=user_active_api_keys_set(email))
    revoked_api_keys = await redis_conn.smembers(name=user_revoked_api_keys_set(email))

    return {
        'success': True,
        'data':
            UserAllDetailsResponse(
                **{k.decode('utf-8'): v.decode('utf-8') for k, v in all_details.items()},
                active_api_keys=[x.decode('utf-8') for x in active_api_keys],
                revoked_api_keys=[x.decode('utf-8') for x in revoked_api_keys],
            ).dict(),
    }


@app.get('/users')
async def get_all_users(
        request: Request,
        response: Response,
):
    redis_conn: aioredis.Redis = request.app.state.redis_pool
    all_users = await redis_conn.smembers(all_users_set())
    return {
        'success': True,
        'data': [x.decode('utf-8') for x in all_users],
    }
