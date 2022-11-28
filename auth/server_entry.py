from typing import Optional, Union
from fastapi import Depends, FastAPI, Request, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from auth.redis_keys import (user_details_htable, all_users_set, user_api_keys_set)
from urllib.parse import urlencode, urljoin
from dynaconf import settings
from auth.data_models import AppOwnerModel, AddApiKeyRequest, UserAllDetailsResponse
import logging
import sys
import coloredlogs
from redis import asyncio as aioredis
import os
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
        user_details = user_cu_request.dict(exclude={'email'})
        api_logger.debug('User details after popping email: %s', user_details)
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

    _ = await redis_conn.sadd(
        user_api_keys_set(email),
        api_key_request.api_key
    )
    if _:
        return {'success': True}
    else:
        return {'success': False}


@app.get('/user/{email}')
async def get_user_details(
        request: Request,
        response: Response,
        email: str
):
    redis_conn: aioredis.Redis = request.app.state.redis_pool
    if not await redis_conn.sismember(all_users_set(), email):
        response.status_code = 400
        return {'success': False}

    all_details = await redis_conn.hgetall(name=user_details_htable(email))
    all_api_keys = await redis_conn.smembers(name=user_api_keys_set(email))
    return UserAllDetailsResponse(
        email=email,
        **{k.decode('utf-8'): v.decode('utf-8') for k, v in all_details.items()},
        api_keys=[x.decode('utf-8') for x in all_api_keys]
    )
