from typing import Optional, Union
from fastapi import Depends, FastAPI, Request, Response, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlencode, urljoin
from dynaconf import settings
import logging
import sys
import coloredlogs
from redis import asyncio as aioredis
import aiohttp
import json
import os
import time
from math import floor
from pydantic import NoneStr
import redis_keys
from redis_conn import RedisPoolCache


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
app = FastAPI(docs_url=None, openapi_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

try:
    os.stat(os.getcwd() + '/static')
except:
    os.mkdir(os.getcwd() + '/static')

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event('startup')
async def startup_boilerplate():
    app.aioredis_pool = RedisPoolCache(pool_size=100)
    await app.aioredis_pool.populate()
    app.redis_pool = app.aioredis_pool._aioredis_pool


@app.post('/register')
async def new_registration(
        request: Request,
        response: Response

):
    pass
