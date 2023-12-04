import asyncio
import json
import os
import time
from turtle import update
from typing import Any
import aiorwlock

from fastapi import FastAPI
from fastapi import Request
from fastapi import Response
from fastapi.middleware.cors import CORSMiddleware
from redis import asyncio as aioredis
from web3 import AsyncHTTPProvider
from web3 import AsyncWeb3

from snapshotter.auth.helpers.data_models import AddApiKeyRequest, WalletAddressRequest
from snapshotter.auth.helpers.data_models import AppOwnerModel
from snapshotter.auth.helpers.data_models import UserAllDetailsResponse
from snapshotter.auth.helpers.redis_conn import RedisPoolCache
from snapshotter.auth.helpers.redis_keys import all_users_set
from snapshotter.auth.helpers.redis_keys import api_key_to_owner_key
from snapshotter.auth.helpers.redis_keys import user_active_api_keys_set
from snapshotter.auth.helpers.redis_keys import user_details_htable
from snapshotter.auth.helpers.redis_keys import user_revoked_api_keys_set
from snapshotter.settings.config import settings
from snapshotter.auth.conf import auth_settings
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential
from snapshotter.utils.default_logger import logger

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


async def write_transaction(w3, address, private_key, contract, function, nonce, chain_id, *args):
    """ Writes a transaction to the blockchain

    Args:
            w3 (web3.Web3): Web3 object
            address (str): The address of the account
            private_key (str): The private key of the account
            contract (web3.eth.contract): Web3 contract object
            function (str): The function to call
            *args: The arguments to pass to the function

    Returns:
            str: The transaction hash
    """

    # Create the function
    func = getattr(contract.functions, function)
    # Get the transaction
    transaction = await func(*args).build_transaction({
        'from': address,
        'gas': 2000000,
        'gasPrice': w3.to_wei('0.001', 'gwei'),
        'nonce': nonce,
        'chainId': chain_id,
    })

    # Sign the transaction
    signed_transaction = w3.eth.account.sign_transaction(
        transaction, private_key=private_key,
    )
    # Send the transaction
    tx_hash = await w3.eth.send_raw_transaction(signed_transaction.rawTransaction)
    # Wait for confirmation
    return tx_hash.hex()

async def update_snapshotter_in_contract(request: Request, protocol_state_contract_addr: str, wallet_address: str, update_flag: bool):
    contract = await get_protocol_state_contract(request, protocol_state_contract_addr)
    async with request.app.state._rwlock.writer_lock:
        _nonce = request.app.state.signer_nonce
        try:
            tx_hash = await write_transaction(
                request.app.state.w3,
                request.app.state.signer_account,
                request.app.state.signer_pkey,
                contract,
                'updateSnapshotters',
                _nonce,
                [request.app.state.w3.to_checksum_address(wallet_address)],
                [update_flag],
            )

            request.app.state.signer_nonce += 1

            api_logger.info(f'submitted transaction with tx_hash: {tx_hash}')

        except Exception as e:
            api_logger.error(f'Exception: {e}')

            if 'nonce' in str(e):
                # sleep for 10 seconds and reset nonce
                time.sleep(10)
                request.app.state.signer_nonce = await request.app.state.w3.eth.get_transaction_count(
                    request.app.state.signer_account,
                )
                api_logger.info(f'nonce reset to: {request.app.state.signer_nonce}')
                raise Exception('nonce error, reset nonce')
            else:
                raise Exception('other error, still retrying')

    receipt = await request.app.state.w3.eth.wait_for_transaction_receipt(tx_hash)

    if receipt['status'] == 0:
        api_logger.info(
            f'tx_hash: {tx_hash} failed, receipt: {receipt}, wallet address: {wallet_address}, update flag: {update_flag}',
        )
        raise Exception('tx receipt error, still retrying')
    else:
        api_logger.info(
            f'tx_hash: {tx_hash} succeeded!, wallet address: {wallet_address}, update flag: {update_flag}',
        )

# add or remove snapshotter
@retry(
    reraise=True,
    retry=retry_if_exception_type(Exception),
    wait=wait_random_exponential(multiplier=1, max=10),
    stop=stop_after_attempt(3),
)
async def update_snapshotter(request: Request, email:str, wallet_address: str, update_flag: bool):
    """
    Submit Snapshot
    """
    update_res = await asyncio.gather(*[update_snapshotter_in_contract(request, each_protocol_state_contract, wallet_address, update_flag) for each_protocol_state_contract in auth_settings.protocol_state_contracts], return_exceptions=True)
    if any([isinstance(x, Exception) for x in update_res]):
        raise Exception('update snapshotter failed')
    async with request.app.state.redis_pool.pipeline(transaction=True) as p:
        await p.hset(
            user_details_htable(email),
            'walletAddress',
            request.app.state.w3.to_checksum_address(wallet_address),
        ).execute()
        

async def get_protocol_state_contract(request: Request, contract_address: str):
    """
    Get Protocol State Contract
    """
    # validate contract address
    if not request.app.state.w3.is_address(contract_address):
        return None

    # get contract object
    if request.app.state.w3.to_checksum_address(contract_address) not in request.app.state.protocol_state_contract_instance_mapping:
        contract = request.app.state.w3.eth.contract(
            address=contract_address, abi=app.state.abi,
        )
        request.app.state.protocol_state_contract_instance_mapping[
            request.app.state.w3.to_checksum_address(contract_address)
        ] = contract
        return contract
    else:
        return request.app.state.protocol_state_contract_instance_mapping[
            request.app.state.w3.to_checksum_address(contract_address)
        ]


@app.on_event('startup')
async def startup_boilerplate():
    app.state.aioredis_pool = RedisPoolCache(pool_size=100)
    await app.state.aioredis_pool.populate()
    app.state.redis_pool = app.state.aioredis_pool._aioredis_pool
    app.state.core_settings = settings
    app.state._rwlock = aiorwlock.RWLock()
    # open pid.json and find the index of pid of the worker
    worker_pid = os.getpid()

    with open('pid.json', 'r') as pid_file:
        data = json.load(pid_file)

        # find the index of the worker in the list
        worker_idx = data.index(worker_pid)

        app.state.signer_account = auth_settings.signers[worker_idx].address
        app.state.signer_pkey = auth_settings.signers[worker_idx].private_key

        # load abi from json file and create contract object
        with open('snapshotter/static/abis/ProtocolContract.json', 'r') as f:
            app.state.abi = json.load(f)
        app.state.w3 = AsyncWeb3(AsyncHTTPProvider(settings.anchor_chain_rpc.full_nodes[0].url))

        
        app.state.signer_nonce = await app.state.w3.eth.get_transaction_count(app.state.signer_account)
        app.state.protocol_state_contract_instance_mapping = {}
        
        # check if signer has enough balance
        balance = await app.state.w3.eth.get_balance(app.state.signer_account)
        # convert to eth
        balance = app.state.w3.from_wei(balance, 'ether')
        if balance < auth_settings.min_signer_balance_eth:
            api_logger.error(f'Signer {app.state.signer_account} has insufficient balance: {balance} ETH')
            exit(1)
        app.state.chain_id = app.state.w3.eth.chain_id
        api_logger.info(
            f'Started worker {worker_idx}, with signer_account: {app.state.signer_account}, signer_nonce: {app.state.signer_nonce}',
        )


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
        if not await redis_conn.sismember(
            all_users_set(),
            user_cu_request.email,
        ):
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


@app.delete('/user/{email}/walletAddress')
async def revoke_wallet_address(
    request: Request,
    response: Response,
    email: str,
):
    redis_conn: aioredis.Redis = request.app.state.redis_pool
    if not await redis_conn.sismember(all_users_set(), email):
        return {'success': False, 'error': 'User does not exists'}

   # TODO: atomic redis update on updating wallet address to False on protocol state contract
    return {'success': True}

@app.post('/user/{email}/walletAddress')
async def add_wallet_address(
    request: Request,
    wallet_address_request: WalletAddressRequest,
    response: Response,
    email: str,
):
    redis_conn: aioredis.Redis = request.app.state.redis_pool
    if not await redis_conn.sismember(all_users_set(), email):
        return {'success': False, 'error': 'User does not exists'}

    _ = await redis_conn.hget(user_details_htable(email), 'walletAddress')
    if _ and _ != b'':
        response.status_code = 403
        return {'success': False, 'error': 'Wallet address already exists'}
    
    
    asyncio.ensure_future(update_snapshotter(request, email, wallet_address_request.wallet_address, True))
    
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

    if not await redis_conn.sismember(
        user_active_api_keys_set(email),
        api_key_request.api_key,
    ):
        return {'success': False, 'error': 'API key not active'}
    elif await redis_conn.sismember(
        user_revoked_api_keys_set(email),
        api_key_request.api_key,
    ):
        return {'success': False, 'error': 'API key already revoked'}
    await redis_conn.smove(
        user_active_api_keys_set(email),
        user_revoked_api_keys_set(email),
        api_key_request.api_key,
    )
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

    active_api_keys = await redis_conn.smembers(
        name=user_active_api_keys_set(email),
    )
    revoked_api_keys = await redis_conn.smembers(
        name=user_revoked_api_keys_set(email),
    )

    return {
        'success': True,
        'data': UserAllDetailsResponse(
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
