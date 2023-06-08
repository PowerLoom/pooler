from fastapi import Depends
from fastapi import FastAPI
from fastapi import Request
from fastapi import Response
from fastapi.middleware.cors import CORSMiddleware
from ipfs_client.main import AsyncIPFSClientSingleton
from redis import asyncio as aioredis
from web3 import Web3

from pooler.auth.helpers.data_models import RateLimitAuthCheck
from pooler.auth.helpers.data_models import UserStatusEnum
from pooler.auth.helpers.helpers import incr_success_calls_count
from pooler.auth.helpers.helpers import inject_rate_limit_fail_response
from pooler.auth.helpers.helpers import rate_limit_auth_check
from pooler.auth.helpers.redis_conn import RedisPoolCache as AuthRedisPoolCache
from pooler.settings.config import settings
from pooler.utils.data_utils import get_project_epoch_snapshot
from pooler.utils.data_utils import get_project_finalized_cid
from pooler.utils.data_utils import get_snapshotter_project_status
from pooler.utils.data_utils import get_snapshotter_status
from pooler.utils.default_logger import logger
from pooler.utils.file_utils import read_json_file
from pooler.utils.redis.rate_limiter import load_rate_limiter_scripts
from pooler.utils.redis.redis_conn import RedisPoolCache
from pooler.utils.redis.redis_keys import project_last_finalized_epoch_key
from pooler.utils.rpc import RpcHelper


REDIS_CONN_CONF = {
    'host': settings.redis.host,
    'port': settings.redis.port,
    'password': settings.redis.password,
    'db': settings.redis.db,
}

# setup logging
rest_logger = logger.bind(module='PowerLoom|CoreAPI')


protocol_state_contract_abi = read_json_file(
    settings.protocol_state.abi,
    rest_logger,
)
protocol_state_contract_address = settings.protocol_state.address

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
    app.state.auth_aioredis_singleton = AuthRedisPoolCache(pool_size=100)
    await app.state.auth_aioredis_singleton.populate()
    app.state.auth_aioredis_pool = (
        app.state.auth_aioredis_singleton._aioredis_pool
    )
    app.state.core_settings = settings
    app.state.local_user_cache = dict()
    await load_rate_limiter_scripts(app.state.auth_aioredis_pool)
    app.state.anchor_rpc_helper = RpcHelper(rpc_settings=settings.anchor_chain_rpc)
    app.state.protocol_state_contract = app.state.anchor_rpc_helper.get_current_node()['web3_client'].eth.contract(
        address=Web3.toChecksumAddress(
            protocol_state_contract_address,
        ),
        abi=protocol_state_contract_abi,
    )
    app.state.ipfs_singleton = AsyncIPFSClientSingleton(settings.ipfs)
    await app.state.ipfs_singleton.init_sessions()
    app.state.ipfs_reader_client = app.state.ipfs_singleton._ipfs_read_client

# Health check endpoint that returns 200 OK


@app.get('/health')
async def health_check():
    return {'status': 'OK'}

# get current epoch


@app.get('/current_epoch')
async def get_current_epoch(
    request: Request,
    response: Response,
    rate_limit_auth_dep: RateLimitAuthCheck = Depends(
        rate_limit_auth_check,
    ),
):
    """
    This endpoint is used to fetch current epoch.
    """
    if not (
        rate_limit_auth_dep.rate_limit_passed and
        rate_limit_auth_dep.authorized and
        rate_limit_auth_dep.owner.active == UserStatusEnum.active
    ):
        return inject_rate_limit_fail_response(rate_limit_auth_dep)

    try:
        [current_epoch_data] = await request.app.state.anchor_rpc_helper.web3_call(
            [request.app.state.protocol_state_contract.functions.currentEpoch()],
            redis_conn=request.app.state.redis_pool,
        )
        current_epoch = {
            'begin': current_epoch_data[0],
            'end': current_epoch_data[1],
            'epochId': current_epoch_data[2],
        }

    except Exception as e:
        rest_logger.exception(
            'Exception in get_current_epoch',
            e=e,
        )
        response.status_code = 500
        return {
            'status': 'error',
            'message': f'Unable to get current epoch, error: {e}',
        }

    auth_redis_conn: aioredis.Redis = request.app.state.auth_aioredis_pool
    await incr_success_calls_count(auth_redis_conn, rate_limit_auth_dep)

    return current_epoch


# get epoch info
@app.get('/epoch/{epoch_id}')
async def get_epoch_info(
    request: Request,
    response: Response,
    epoch_id: int,
    rate_limit_auth_dep: RateLimitAuthCheck = Depends(
        rate_limit_auth_check,
    ),
):
    """
    This endpoint is used to fetch epoch info for a given epoch_id.
    """
    if not (
        rate_limit_auth_dep.rate_limit_passed and
        rate_limit_auth_dep.authorized and
        rate_limit_auth_dep.owner.active == UserStatusEnum.active
    ):
        return inject_rate_limit_fail_response(rate_limit_auth_dep)

    try:
        [epoch_info_data] = await request.app.state.anchor_rpc_helper.web3_call(
            [request.app.state.protocol_state_contract.functions.epochInfo(epoch_id)],
            redis_conn=request.app.state.redis_pool,
        )
        epoch_info = {
            'timestamp': epoch_info_data[0],
            'blocknumber': epoch_info_data[1],
            'epochEnd': epoch_info_data[2],
        }

    except Exception as e:
        rest_logger.exception(
            'Exception in get_current_epoch',
            e=e,
        )
        response.status_code = 500
        return {
            'status': 'error',
            'message': f'Unable to get current epoch, error: {e}',
        }

    auth_redis_conn: aioredis.Redis = request.app.state.auth_aioredis_pool
    await incr_success_calls_count(auth_redis_conn, rate_limit_auth_dep)

    return epoch_info


@app.get('/last_finalized_epoch/{project_id}')
async def get_project_last_finalized_epoch_info(
    request: Request,
    response: Response,
    project_id: str,
    rate_limit_auth_dep: RateLimitAuthCheck = Depends(
        rate_limit_auth_check,
    ),
):
    """
    This endpoint is used to fetch epoch info for the last finalized epoch for a given project.
    """
    if not (
        rate_limit_auth_dep.rate_limit_passed and
        rate_limit_auth_dep.authorized and
        rate_limit_auth_dep.owner.active == UserStatusEnum.active
    ):
        return inject_rate_limit_fail_response(rate_limit_auth_dep)

    try:

        # get project last finalized epoch from redis
        project_last_finalized_epoch = await request.app.state.redis_pool.get(
            project_last_finalized_epoch_key(project_id),
        )

        if project_last_finalized_epoch is None:
            response.status_code = 404
            return {
                'status': 'error',
                'message': f'Unable to find last finalized epoch for project {project_id}',
            }

        project_last_finalized_epoch = int(project_last_finalized_epoch.decode('utf-8'))

        [epoch_info_data] = await request.app.state.anchor_rpc_helper.web3_call(
            [request.app.state.protocol_state_contract.functions.epochInfo(project_last_finalized_epoch)],
            redis_conn=request.app.state.redis_pool,
        )
        epoch_info = {
            'epochId': project_last_finalized_epoch,
            'timestamp': epoch_info_data[0],
            'blocknumber': epoch_info_data[1],
            'epochEnd': epoch_info_data[2],
        }

    except Exception as e:
        rest_logger.exception(
            'Exception in get_project_last_finalized_epoch_info',
            e=e,
        )
        response.status_code = 500
        return {
            'status': 'error',
            'message': f'Unable to get last finalized epoch for project {project_id}, error: {e}',
        }

    auth_redis_conn: aioredis.Redis = request.app.state.auth_aioredis_pool
    await incr_success_calls_count(auth_redis_conn, rate_limit_auth_dep)

    return epoch_info

# get data for epoch_id, project_id


@app.get('/data/{epoch_id}/{project_id}/')
async def get_data_for_project_id_epoch_id(
    request: Request,
    response: Response,
    project_id: str,
    epoch_id: int,
    rate_limit_auth_dep: RateLimitAuthCheck = Depends(
        rate_limit_auth_check,
    ),
):
    """
    This endpoint is used to fetch data for a given project_id and epoch_id.
    """
    if not (
        rate_limit_auth_dep.rate_limit_passed and
        rate_limit_auth_dep.authorized and
        rate_limit_auth_dep.owner.active == UserStatusEnum.active
    ):
        return inject_rate_limit_fail_response(rate_limit_auth_dep)

    try:
        data = await get_project_epoch_snapshot(
            request.app.state.redis_pool,
            request.app.state.protocol_state_contract,
            request.app.state.anchor_rpc_helper,
            request.app.state.ipfs_reader_client,
            epoch_id,
            project_id,
        )
    except Exception as e:
        rest_logger.exception(
            'Exception in get_data_for_project_id_epoch_id',
            e=e,
        )
        response.status_code = 500
        return {
            'status': 'error',
            'message': f'Unable to get data for project_id: {project_id},'
            f' epoch_id: {epoch_id}, error: {e}',
        }

    if not data:
        response.status_code = 404
        return {
            'status': 'error',
            'message': f'No data found for project_id: {project_id},'
            f' epoch_id: {epoch_id}',
        }
    auth_redis_conn: aioredis.Redis = request.app.state.auth_aioredis_pool
    await incr_success_calls_count(auth_redis_conn, rate_limit_auth_dep)

    return data

# get finalized cid for epoch_id, project_id


@app.get('/cid/{epoch_id}/{project_id}/')
async def get_finalized_cid_for_project_id_epoch_id(
    request: Request,
    response: Response,
    project_id: str,
    epoch_id: int,
    rate_limit_auth_dep: RateLimitAuthCheck = Depends(
        rate_limit_auth_check,
    ),
):
    """
    This endpoint is used to fetch finalized cid for a given project_id and epoch_id.
    """
    if not (
        rate_limit_auth_dep.rate_limit_passed and
        rate_limit_auth_dep.authorized and
        rate_limit_auth_dep.owner.active == UserStatusEnum.active
    ):
        return inject_rate_limit_fail_response(rate_limit_auth_dep)

    try:
        data = await get_project_finalized_cid(
            request.app.state.redis_pool,
            request.app.state.protocol_state_contract,
            request.app.state.anchor_rpc_helper,
            epoch_id,
            project_id,
        )
    except Exception as e:
        rest_logger.exception(
            'Exception in get_finalized_cid_for_project_id_epoch_id',
            e=e,
        )
        response.status_code = 500
        return {
            'status': 'error',
            'message': f'Unable to get finalized cid for project_id: {project_id},'
            f' epoch_id: {epoch_id}, error: {e}',
        }

    if not data:
        response.status_code = 404
        return {
            'status': 'error',
            'message': f'No finalized cid found for project_id: {project_id},'
            f' epoch_id: {epoch_id}',
        }
    auth_redis_conn: aioredis.Redis = request.app.state.auth_aioredis_pool
    await incr_success_calls_count(auth_redis_conn, rate_limit_auth_dep)

    return data


@app.get('/internal/snapshotter/status')
async def get_snapshotter_overall_status(
    request: Request,
    response: Response,
    rate_limit_auth_dep: RateLimitAuthCheck = Depends(
        rate_limit_auth_check,
    ),
):
    if not (
        rate_limit_auth_dep.rate_limit_passed and
        rate_limit_auth_dep.authorized and
        rate_limit_auth_dep.owner.active == UserStatusEnum.active
    ):
        return inject_rate_limit_fail_response(rate_limit_auth_dep)

    try:
        snapshotter_status = await get_snapshotter_status(
            request.app.state.redis_pool,
        )
    except Exception as e:
        rest_logger.exception(
            'Exception in get_snapshotter_overall_status',
            e=e,
        )
        response.status_code = 500
        return {
            'status': 'error',
            'message': f'Unable to get snapshotter status, error: {e}',
        }

    auth_redis_conn: aioredis.Redis = request.app.state.auth_aioredis_pool
    await incr_success_calls_count(auth_redis_conn, rate_limit_auth_dep)

    return snapshotter_status


@app.get('/internal/snapshotter/status/{project_id}')
async def get_snapshotter_project_level_status(
    request: Request,
    response: Response,
    project_id: str,
    rate_limit_auth_dep: RateLimitAuthCheck = Depends(
        rate_limit_auth_check,
    ),
):
    if not (
        rate_limit_auth_dep.rate_limit_passed and
        rate_limit_auth_dep.authorized and
        rate_limit_auth_dep.owner.active == UserStatusEnum.active
    ):
        return inject_rate_limit_fail_response(rate_limit_auth_dep)

    try:
        snapshotter_project_status = await get_snapshotter_project_status(
            request.app.state.redis_pool,
            project_id=project_id,
        )
    except Exception as e:
        rest_logger.exception(
            'Exception in get_snapshotter_project_level_status',
            e=e,
        )
        response.status_code = 500
        return {
            'status': 'error',
            'message': f'Unable to get snapshotter status for project_id: {project_id}, error: {e}',
        }

    if not snapshotter_project_status:
        response.status_code = 404
        return {
            'status': 'error',
            'message': f'No snapshotter status found for project_id: {project_id}',
        }

    auth_redis_conn: aioredis.Redis = request.app.state.auth_aioredis_pool
    await incr_success_calls_count(auth_redis_conn, rate_limit_auth_dep)

    return snapshotter_project_status
