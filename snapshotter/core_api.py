import json
from typing import List

from fastapi import Depends
from fastapi import FastAPI
from fastapi import Request
from fastapi import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi_pagination import add_pagination
from fastapi_pagination import Page
from fastapi_pagination import paginate
from ipfs_client.main import AsyncIPFSClientSingleton
from pydantic import Field
from redis import asyncio as aioredis
from web3 import Web3

from snapshotter.auth.helpers.data_models import RateLimitAuthCheck
from snapshotter.auth.helpers.data_models import UserStatusEnum
from snapshotter.auth.helpers.helpers import incr_success_calls_count
from snapshotter.auth.helpers.helpers import inject_rate_limit_fail_response
from snapshotter.auth.helpers.helpers import rate_limit_auth_check
from snapshotter.auth.helpers.redis_conn import RedisPoolCache as AuthRedisPoolCache
from snapshotter.settings.config import settings
from snapshotter.utils.data_utils import get_project_epoch_snapshot
from snapshotter.utils.data_utils import get_project_finalized_cid
from snapshotter.utils.data_utils import get_snapshotter_project_status
from snapshotter.utils.data_utils import get_snapshotter_status
from snapshotter.utils.default_logger import logger
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.models.data_models import SnapshotterEpochProcessingReportItem
from snapshotter.utils.models.data_models import SnapshotterStates
from snapshotter.utils.models.data_models import SnapshotterStateUpdate
from snapshotter.utils.models.data_models import TaskStatusRequest
from snapshotter.utils.redis.rate_limiter import load_rate_limiter_scripts
from snapshotter.utils.redis.redis_conn import RedisPoolCache
from snapshotter.utils.redis.redis_keys import active_status_key
from snapshotter.utils.redis.redis_keys import epoch_id_epoch_released_key
from snapshotter.utils.redis.redis_keys import epoch_id_project_to_state_mapping
from snapshotter.utils.redis.redis_keys import epoch_process_report_cached_key
from snapshotter.utils.redis.redis_keys import project_last_finalized_epoch_key
from snapshotter.utils.rpc import RpcHelper


REDIS_CONN_CONF = {
    'host': settings.redis.host,
    'port': settings.redis.port,
    'password': settings.redis.password,
    'db': settings.redis.db,
}

# setup logging
rest_logger = logger.bind(module='Powerloom|CoreAPI')


protocol_state_contract_abi = read_json_file(
    settings.protocol_state.abi,
    rest_logger,
)
protocol_state_contract_address = settings.protocol_state.address

# setup CORS origins stuff
origins = ['*']
app = FastAPI()
# for pagination of epoch processing status reports
Page = Page.with_custom_options(
    size=Field(10, ge=1, le=30),
)
add_pagination(app)
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
    app.state.epoch_size = 0


# Health check endpoint
@app.get('/health')
async def health_check(
    request: Request,
    response: Response,
):
    redis_conn: aioredis.Redis = request.app.state.redis_pool
    _ = await redis_conn.get(active_status_key)
    if _:
        active_status = bool(int(_))
        if not active_status:
            response.status_code = 503
            return {
                'status': 'error',
                'message': 'Snapshotter is not active',
            }
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
            # find from contract
            epoch_finalized = False
            [cur_epoch] = await request.app.state.anchor_rpc_helper.web3_call(
                [request.app.state.protocol_state_contract.functions.currentEpoch()],
                redis_conn=request.app.state.redis_pool,
            )
            epoch_id = int(cur_epoch[2])
            while not epoch_finalized and epoch_id >= 0:
                # get finalization status
                [epoch_finalized_contract] = await request.app.state.anchor_rpc_helper.web3_call(
                    [request.app.state.protocol_state_contract.functions.snapshotStatus(project_id, epoch_id)],
                    redis_conn=request.app.state.redis_pool,
                )
                if epoch_finalized_contract[0]:
                    epoch_finalized = True
                    project_last_finalized_epoch = epoch_id
                    await request.app.state.redis_pool.set(
                        project_last_finalized_epoch_key(project_id),
                        project_last_finalized_epoch,
                    )
                else:
                    epoch_id -= 1
                    if epoch_id < 0:
                        response.status_code = 404
                        return {
                            'status': 'error',
                            'message': f'Unable to find last finalized epoch for project {project_id}',
                        }
        else:
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
    data: bool = False,
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
            with_data=data,
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

    return snapshotter_project_status.dict(exclude_none=True, exclude_unset=True)


@app.get('/internal/snapshotter/epochProcessingStatus')
async def get_snapshotter_epoch_processing_status(
    request: Request,
    response: Response,
    rate_limit_auth_dep: RateLimitAuthCheck = Depends(
        rate_limit_auth_check,
    ),
) -> Page[SnapshotterEpochProcessingReportItem]:
    if not (
        rate_limit_auth_dep.rate_limit_passed and
        rate_limit_auth_dep.authorized and
        rate_limit_auth_dep.owner.active == UserStatusEnum.active
    ):
        return inject_rate_limit_fail_response(rate_limit_auth_dep)
    redis_conn: aioredis.Redis = request.app.state.redis_pool
    _ = await redis_conn.get(epoch_process_report_cached_key)
    if _:
        epoch_processing_final_report = list(
            map(
                lambda x: SnapshotterEpochProcessingReportItem.parse_obj(x),
                json.loads(_),
            ),
        )
        return paginate(epoch_processing_final_report)
    epoch_processing_final_report: List[SnapshotterEpochProcessingReportItem] = list()
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
    current_epoch_id = current_epoch['epochId']
    if request.app.state.epoch_size == 0:
        [epoch_size] = await request.app.state.anchor_rpc_helper.web3_call(
            [request.app.state.protocol_state_contract.functions.EPOCH_SIZE()],
            redis_conn=request.app.state.redis_pool,
        )
        rest_logger.info(f'Setting Epoch size: {epoch_size}')
        request.app.state.epoch_size = epoch_size
    for epoch_id in range(current_epoch_id, current_epoch_id - 30 - 1, -1):
        epoch_specific_report = SnapshotterEpochProcessingReportItem.construct()
        epoch_release_status = await redis_conn.get(
            epoch_id_epoch_released_key(epoch_id=epoch_id),
        )
        if not epoch_release_status:
            continue
        epoch_specific_report.epochId = epoch_id
        if epoch_id == current_epoch_id:
            epoch_specific_report.epochEnd = current_epoch['end']
        else:
            epoch_specific_report.epochEnd = current_epoch['end'] - (
                (current_epoch_id - epoch_id) * request.app.state.epoch_size
            )
            rest_logger.debug(
                f'Epoch End for epoch_id: {epoch_id} is {epoch_specific_report.epochEnd}',
            )
        epoch_specific_report.transitionStatus = dict()
        if epoch_release_status:
            epoch_specific_report.transitionStatus['EPOCH_RELEASED'] = SnapshotterStateUpdate(
                status='success', timestamp=int(epoch_release_status),
            )
        else:
            epoch_specific_report.transitionStatus['EPOCH_RELEASED'] = None
        for state in SnapshotterStates:
            state_report_entries = await redis_conn.hgetall(
                name=epoch_id_project_to_state_mapping(epoch_id=epoch_id, state_id=state.value),
            )
            if state_report_entries:
                project_state_report_entries = dict()
                epoch_specific_report.transitionStatus[state.value] = dict()
                project_state_report_entries = {
                    project_id.decode('utf-8'): SnapshotterStateUpdate.parse_raw(project_state_entry)
                    for project_id, project_state_entry in state_report_entries.items()
                }
                epoch_specific_report.transitionStatus[state.value] = project_state_report_entries
            else:
                epoch_specific_report.transitionStatus[state.value] = None
        epoch_processing_final_report.append(epoch_specific_report)
    await redis_conn.set(
        epoch_process_report_cached_key,
        json.dumps(list(map(lambda x: x.dict(), epoch_processing_final_report))),
        ex=60,
    )
    return paginate(epoch_processing_final_report)


@app.post('/task_status')
async def get_task_status_post(
    request: Request,
    response: Response,
    task_status_request: TaskStatusRequest,
    rate_limit_auth_dep: RateLimitAuthCheck = Depends(
        rate_limit_auth_check,
    ),
):
    """
    This endpoint is used to fetch task status for a given task_type and wallet_address.
    """

    if not (
        rate_limit_auth_dep.rate_limit_passed and
        rate_limit_auth_dep.authorized and
        rate_limit_auth_dep.owner.active == UserStatusEnum.active
    ):
        return inject_rate_limit_fail_response(rate_limit_auth_dep)

    # check wallet address is valid EVM address
    try:
        Web3.toChecksumAddress(task_status_request.wallet_address)
    except:
        response.status_code = 400
        return {
            'status': 'error',
            'message': f'Invalid wallet address: {task_status_request.wallet_address}',
        }

    project_id = f'{task_status_request.task_type}:{task_status_request.wallet_address.lower()}:{settings.namespace}'
    try:

        # check redis first, if doesn't exist, fetch from contract
        last_finalized_epoch = await request.app.state.redis_pool.get(
            project_last_finalized_epoch_key(project_id),
        )

        if last_finalized_epoch is None:

            [last_finalized_epoch] = await request.app.state.anchor_rpc_helper.web3_call(
                [request.app.state.protocol_state_contract.functions.lastFinalizedSnapshot(project_id)],
                redis_conn=request.app.state.redis_pool,
            )
            # cache it in redis
            if last_finalized_epoch != 0:
                await request.app.state.redis_pool.set(
                    project_last_finalized_epoch_key(project_id),
                    last_finalized_epoch,
                )
        else:
            last_finalized_epoch = int(last_finalized_epoch.decode('utf-8'))

    except Exception as e:
        rest_logger.exception(
            'Exception in get_current_epoch',
            e=e,
        )
        response.status_code = 500
        return {
            'status': 'error',
            'message': f'Unable to get last_finalized_epoch, error: {e}',
        }
    else:

        auth_redis_conn: aioredis.Redis = request.app.state.auth_aioredis_pool
        await incr_success_calls_count(auth_redis_conn, rate_limit_auth_dep)

        if last_finalized_epoch > 0:
            return {
                'completed': True,
                'message': f'Task {task_status_request.task_type} for wallet {task_status_request.wallet_address} was completed in epoch {last_finalized_epoch}',
            }
        else:
            return {
                'completed': False,
                'message': f'Task {task_status_request.task_type} for wallet {task_status_request.wallet_address} is not completed yet',
            }
