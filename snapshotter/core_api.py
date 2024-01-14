from fastapi import FastAPI
from fastapi import Request
from fastapi import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi_pagination import add_pagination
from fastapi_pagination import Page
from ipfs_client.main import AsyncIPFSClientSingleton
from pydantic import Field
from web3 import Web3

from snapshotter.settings.config import settings
from snapshotter.utils.data_utils import get_project_epoch_snapshot
from snapshotter.utils.data_utils import get_project_finalized_cid
from snapshotter.utils.default_logger import logger
from snapshotter.utils.file_utils import read_json_file
from snapshotter.utils.models.data_models import TaskStatusRequest
from snapshotter.utils.rpc import RpcHelper


# setup logging
rest_logger = logger.bind(module='CoreAPI')


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
    """
    This function initializes various state variables and caches required for the application to function properly.
    """
    app.state.core_settings = settings
    app.state.local_user_cache = dict()
    app.state.anchor_rpc_helper = RpcHelper(rpc_settings=settings.anchor_chain_rpc)
    app.state.protocol_state_contract = app.state.anchor_rpc_helper.get_current_node()['web3_client'].eth.contract(
        address=Web3.to_checksum_address(
            protocol_state_contract_address,
        ),
        abi=protocol_state_contract_abi,
    )

    if not settings.ipfs.url:
        rest_logger.warning('IPFS url not set, /data API endpoint will be unusable!')
    else:
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
    """
    Endpoint to check the health of the Snapshotter service.

    Parameters:
    request (Request): The incoming request object.
    response (Response): The outgoing response object.

    Returns:
    dict: A dictionary containing the status of the service.
    """
    return {'status': 'OK'}


@app.get('/current_epoch')
async def get_current_epoch(
    request: Request,
    response: Response,
):
    """
    Get the current epoch data from the protocol state contract.

    Args:
        request (Request): The incoming request object.
        response (Response): The outgoing response object.

    Returns:
        dict: A dictionary containing the current epoch data.
    """
    try:
        [current_epoch_data] = await request.app.state.anchor_rpc_helper.web3_call(
            [request.app.state.protocol_state_contract.functions.currentEpoch()],
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

    return current_epoch


@app.get('/epoch/{epoch_id}')
async def get_epoch_info(
    request: Request,
    response: Response,
    epoch_id: int,
):
    """
    Get epoch information for a given epoch ID.

    Args:
        request (Request): The incoming request object.
        response (Response): The outgoing response object.
        epoch_id (int): The epoch ID for which to retrieve information.

    Returns:
        dict: A dictionary containing epoch information including timestamp, block number, and epoch end.
    """
    try:
        [epoch_info_data] = await request.app.state.anchor_rpc_helper.web3_call(
            [request.app.state.protocol_state_contract.functions.epochInfo(epoch_id)],
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

    return epoch_info


@app.get('/last_finalized_epoch/{project_id}')
async def get_project_last_finalized_epoch_info(
    request: Request,
    response: Response,
    project_id: str,
):
    """
    Get the last finalized epoch information for a given project.

    Args:
        request (Request): The incoming request object.
        response (Response): The outgoing response object.
        project_id (str): The ID of the project to get the last finalized epoch information for.

    Returns:
        dict: A dictionary containing the last finalized epoch information for the given project.
    """

    try:

        # find from contract
        epoch_finalized = False
        [cur_epoch] = await request.app.state.anchor_rpc_helper.web3_call(
            [request.app.state.protocol_state_contract.functions.currentEpoch()],
        )
        epoch_id = int(cur_epoch[2])
        while not epoch_finalized and epoch_id >= 0:
            # get finalization status
            [epoch_finalized_contract] = await request.app.state.anchor_rpc_helper.web3_call(
                [request.app.state.protocol_state_contract.functions.snapshotStatus(project_id, epoch_id)],
            )
            if epoch_finalized_contract[0]:
                epoch_finalized = True
                project_last_finalized_epoch = epoch_id
            else:
                epoch_id -= 1
                if epoch_id < 0:
                    response.status_code = 404
                    return {
                        'status': 'error',
                        'message': f'Unable to find last finalized epoch for project {project_id}',
                    }
        [epoch_info_data] = await request.app.state.anchor_rpc_helper.web3_call(
            [request.app.state.protocol_state_contract.functions.epochInfo(project_last_finalized_epoch)],
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

    return epoch_info


# get data for epoch_id, project_id
@app.get('/data/{epoch_id}/{project_id}/')
async def get_data_for_project_id_epoch_id(
    request: Request,
    response: Response,
    project_id: str,
    epoch_id: int,
):
    """
    Get data for a given project and epoch ID.

    Args:
        request (Request): The incoming request.
        response (Response): The outgoing response.
        project_id (str): The ID of the project.
        epoch_id (int): The ID of the epoch.

    Returns:
        dict: The data for the given project and epoch ID.
    """
    if not settings.ipfs.url:
        response.status_code = 500
        return {
            'status': 'error',
            'message': f'IPFS url not set, /data API endpoint is unusable, please use /cid endpoint instead!',
        }
    try:
        data = await get_project_epoch_snapshot(
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
    return data


# get finalized cid for epoch_id, project_id
@app.get('/cid/{epoch_id}/{project_id}/')
async def get_finalized_cid_for_project_id_epoch_id(
    request: Request,
    response: Response,
    project_id: str,
    epoch_id: int,
):
    """
    Get finalized cid for a given project_id and epoch_id.

    Args:
        request (Request): The incoming request.
        response (Response): The outgoing response.
        project_id (str): The project id.
        epoch_id (int): The epoch id.

    Returns:
        dict: The finalized cid for the given project_id and epoch_id.
    """

    try:
        data = await get_project_finalized_cid(
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

    return data


@app.post('/task_status')
async def get_task_status_post(
    request: Request,
    response: Response,
    task_status_request: TaskStatusRequest,
):
    """
    Endpoint to get the status of a task for a given wallet address.

    Args:
        request (Request): The incoming request object.
        response (Response): The outgoing response object.
        task_status_request (TaskStatusRequest): The request body containing the task type and wallet address.

    Returns:
        dict: A dictionary containing the status of the task and a message.
    """
    # check wallet address is valid EVM address
    try:
        Web3.to_checksum_address(task_status_request.wallet_address)
    except:
        response.status_code = 400
        return {
            'status': 'error',
            'message': f'Invalid wallet address: {task_status_request.wallet_address}',
        }

    project_id = f'{task_status_request.task_type}:{task_status_request.wallet_address.lower()}:{settings.namespace}'
    try:

        [last_finalized_epoch] = await request.app.state.anchor_rpc_helper.web3_call(
            [request.app.state.protocol_state_contract.functions.lastFinalizedSnapshot(project_id)],
        )

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
