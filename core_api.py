from typing import Optional
from urllib.parse import urljoin
from rate_limiter import load_rate_limiter_scripts
import logging
import sys
import json
import os
from fastapi import Depends, FastAPI, Request, Response, Query
from eth_utils import to_checksum_address
from auth.helpers import rate_limit_auth_check, inject_rate_limit_fail_response, incr_success_calls_count
from auth.redis_conn import RedisPoolCache as AuthRedisPoolCache
from auth.data_models import RateLimitAuthCheck, UserStatusEnum
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dynaconf import settings
import coloredlogs
from redis import asyncio as aioredis
import aiohttp
from web3 import Web3

import redis_keys
from redis_conn import RedisPoolCache
from file_utils import read_json_file
from redis_keys import (
    uniswap_pair_cached_recent_logs, uniswap_pair_contract_tokens_addresses,
    uniswap_V2_summarized_snapshots_zset, uniswap_V2_snapshot_at_blockheight,
    uniswap_v2_daily_stats_snapshot_zset, uniswap_V2_daily_stats_at_blockheight,
    uniswap_v2_tokens_snapshot_zset, uniswap_V2_tokens_at_blockheight

)
from utility_functions import (
    number_to_abbreviated_string,
    retrieve_payload_data
)

REDIS_CONN_CONF = {
    "host": settings['redis']['host'],
    "port": settings['redis']['port'],
    "password": settings['redis']['password'],
    "db": settings['redis']['db']
}

SNAPSHOT_STATUS_MAP = {
    1: "SNAPSHOT_COMMIT_PENDING",
    2: "TX_ACK_PENDING",
    3: "TX_CONFIRMATION_PENDING",
    4: "TX_CONFIRMED"
}

formatter = logging.Formatter(u"%(levelname)-8s %(name)-4s %(asctime)s,%(msecs)d %(module)s-%(funcName)s: %(message)s")

stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setLevel(logging.DEBUG)
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.ERROR)

rest_logger = logging.getLogger(__name__)
rest_logger.setLevel(logging.DEBUG)
rest_logger.addHandler(stdout_handler)
rest_logger.addHandler(stderr_handler)
coloredlogs.install(level='DEBUG', logger=rest_logger, stream=sys.stdout)

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

try:
    os.stat(os.getcwd() + '/static')
except:
    os.mkdir(os.getcwd() + '/static')

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event('startup')
async def startup_boilerplate():
    app.state.aioredis_pool = RedisPoolCache(pool_size=100)
    await app.state.aioredis_pool.populate()
    app.state.redis_pool = app.state.aioredis_pool._aioredis_pool
    app.state.auth_aioredis_singleton = AuthRedisPoolCache(pool_size=100)
    await app.state.auth_aioredis_singleton.populate()
    app.state.auth_aioredis_pool = app.state.auth_aioredis_singleton._aioredis_pool
    app.state.core_settings = settings
    app.state.local_user_cache = dict()
    await load_rate_limiter_scripts(app.state.auth_aioredis_pool)


def project_namespace_inject(request: Request, stream: str = Query(default='pair_total_reserves')):
    """
        This dependency injection is meant to support multiple 'streams' of snapshots submitted to Audit Protocol core.
        for eg. pair total reserves, pair trades etc. Effectively, it injects namespaces into a project ID
    """
    pair_contract_address = request.path_params['pair_contract_address']
    audit_project_id = f'uniswap_pairContract_{stream}_{pair_contract_address}_{settings.NAMESPACE}'
    return audit_project_id


# TODO: This will not be required unless we are serving archived data.
async def save_request_data(
        request: Request,
        request_id: str,
        max_count: int,
        from_height: int,
        to_height: int,
        data,
        project_id: str,
):
    # Acquire redis connection
    request_info_key = f"pendingRequestInfo:{request_id}"
    redis_conn = await request.app.redis_pool
    request_info_data = {
        'maxCount': max_count,
        'fromHeight': from_height,
        'toHeight': to_height,
        'data': data,
        'projectId': project_id
    }
    request_info_json = json.dumps(request_info_data)
    _ = await redis_conn.set(request_info_key, request_info_json)


async def delete_request_data(
        request: Request,
        request_id: str
):
    request_info_key = f"pendingRequestInfo:{request_id}"
    redis_conn = await request.app.redis_pool

    # Delete the request info data
    _ = await redis_conn.delete(key=request_info_key)


@app.get('/snapshots/{pair_contract_address:str}')
async def get_past_snapshots(
        request: Request,
        response: Response,
        maxCount: Optional[int] = Query(None),
        audit_project_id: str = Depends(project_namespace_inject),
        data: Optional[str] = Query('false'),
        rate_limit_auth_dep: RateLimitAuthCheck = Depends(rate_limit_auth_check)
):
    if not (
            rate_limit_auth_dep.rate_limit_passed and
            rate_limit_auth_dep.authorized and
            rate_limit_auth_dep.owner.active == UserStatusEnum.active
    ):
        return inject_rate_limit_fail_response(rate_limit_auth_dep)
    if maxCount > 100:
        return {
            "error": "Data being queried is more than 100 snapshots. Querying data for upto last 100 snapshots is supported."}
    max_count = 10 if not maxCount else maxCount
    last_block_height_url = urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL, f'/{audit_project_id}/payloads/height')
    async with aiohttp.ClientSession() as session:
        async with session.get(url=last_block_height_url) as resp:
            rest_json = await resp.json()
            last_block_height = rest_json.get('height')
    to_block = last_block_height
    if to_block < max_count or max_count == -1:
        from_block = 1
    else:
        from_block = to_block - (max_count - 1)
    if not data:
        data = 'false'
    if not (data.lower() == 'true' or data.lower() == 'false'):
        data = False
    else:
        data = data.lower()
    query_params = {'from_height': from_block, 'to_height': to_block, 'data': data}
    range_fetch_url = urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL, f'/{audit_project_id}/payloads')
    async with aiohttp.ClientSession() as session:
        async with session.get(url=range_fetch_url, params=query_params) as resp:
            resp_json = await resp.json()
            if isinstance(resp_json, dict):
                if 'requestId' in resp_json.keys():
                    # Save the data for this requestId
                    _ = await save_request_data(
                        request=request,
                        request_id=resp_json['requestId'],
                        max_count=max_count,
                        from_height=from_block,
                        to_height=to_block,
                        project_id=audit_project_id,
                        data=data
                    )
            auth_redis_conn: aioredis.Redis = request.app.state.auth_aioredis_pool
            await incr_success_calls_count(auth_redis_conn, rate_limit_auth_dep)
            return resp_json


@app.get('/pair_address')
async def get_pair_contract_from_tokens(
        request: Request,
        response: Response,
        token0: str,
        token1: str,
        rate_limit_auth_dep: RateLimitAuthCheck = Depends(rate_limit_auth_check)

):
    if not (
            rate_limit_auth_dep.rate_limit_passed and
            rate_limit_auth_dep.authorized and
            rate_limit_auth_dep.owner.active == UserStatusEnum.active
    ):
        return inject_rate_limit_fail_response(rate_limit_auth_dep)

    redis_conn: aioredis.Redis = request.app.state.redis_pool
    token0_normalized = to_checksum_address(token0)
    token1_normalized = to_checksum_address(token1)
    pair_return = None
    pair1 = await redis_conn.hget(redis_keys.uniswap_tokens_pair_map, f'{token0_normalized}-{token1_normalized}')
    if not pair1:
        pair2 = await redis_conn.hget(redis_keys.uniswap_tokens_pair_map, f'{token1_normalized}-{token0_normalized}')
        if pair2:
            pair_return = pair2
    elif pair1.decode('utf-8') == '0x0000000000000000000000000000000000000000':
        pass  # do nothing
    auth_redis_conn: aioredis.Redis = request.app.state.auth_aioredis_pool
    await incr_success_calls_count(auth_redis_conn, rate_limit_auth_dep)
    return {
        'data': {
            'pairContractAddress': None if not pair_return else pair_return.decode('utf-8')
        }
    }


@app.get('/v2-pair/{pair_contract_address}')
async def get_single_v2_pair_data(
        request: Request,
        response: Response,
        pair_contract_address: str,
        rate_limit_auth_dep: RateLimitAuthCheck = Depends(rate_limit_auth_check)
):
    if not (
            rate_limit_auth_dep.rate_limit_passed and
            rate_limit_auth_dep.authorized and
            rate_limit_auth_dep.owner.active == UserStatusEnum.active
    ):
        return inject_rate_limit_fail_response(rate_limit_auth_dep)
    redis_conn = request.app.state.redis_pool
    latest_v2_summary_snapshot = await redis_conn.zrevrange(
        name=uniswap_V2_summarized_snapshots_zset,
        start=0,
        end=0,
        withscores=True
    )
    if len(latest_v2_summary_snapshot) < 1:
        return {'data': None}

    latest_snapshot_cid_details, latest_snapshot_blockheight = latest_v2_summary_snapshot[0]
    latest_payload = json.loads(latest_snapshot_cid_details.decode('utf-8'))
    latest_payload_cid = latest_payload.get("cid")

    v2_pairs_snapshot_data = await redis_conn.get(
        name=uniswap_V2_snapshot_at_blockheight.format(int(latest_snapshot_blockheight))
    )
    if not v2_pairs_snapshot_data:
        # fetch from ipfs
        v2_pairs_snapshot_data = await retrieve_payload_data(latest_payload_cid, redis_conn)

    auth_redis_conn: aioredis.Redis = request.app.state.auth_aioredis_pool
    await incr_success_calls_count(auth_redis_conn, rate_limit_auth_dep)

    # even ipfs doesn't have the data, return empty
    if not v2_pairs_snapshot_data:
        return {'data': None}

    pair_entry_filter = filter(
        lambda x: x['contractAddress'].lower() == pair_contract_address.lower(),
        json.loads(v2_pairs_snapshot_data)['data']
    )
    try:
        pair_snapshot_data = next(pair_entry_filter)
    except StopIteration:
        return {'data': None}
    else:
        return {'data': pair_snapshot_data}

