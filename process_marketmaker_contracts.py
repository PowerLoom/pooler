from multiprocessing import Process
from urllib.parse import urljoin
from bounded_pool_executor import BoundedThreadPoolExecutor
from redis import Redis
from redis_conn import provide_redis_conn
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception
from helper_functions import FailedRequestToMaticVigil, cache_markets_data
from helper_functions import handle_failed_maticvigil_exception, acquire_threading_semaphore
from eth_account.account import Account
from eth_account.messages import encode_defunct
from dynaconf import settings
from concurrent.futures import as_completed
import setproctitle
import os
import time
import threading
import json
import logging, logging.handlers
import sys
import requests
import psutil
import coloredlogs
import aiohttp
import helper_functions

""" Initialize the loggers """

REDIS_CONN_CONF = {
    "host": settings['REDIS']['HOST'],
    "port": settings['REDIS']['PORT'],
    "password": settings['REDIS']['PASSWORD'],
    "db": settings['REDIS']['DB']
}


@retry(
    wait=wait_exponential(min=2, max=18, multiplier=1),
    stop=stop_after_attempt(6),
    retry=retry_if_exception(FailedRequestToMaticVigil)
)
def login():
    """
    This function is used to get a list of all contracts
    """
    msg = "get contracts list"
    private_key = settings.MATIC_VIGIL_KEYS.PRIVATE_KEY
    hash_msg = encode_defunct(text=msg)
    sig = Account.sign_message(hash_msg, private_key).signature.hex()
    key = settings.MATIC_VIGIL_KEYS.API_KEY
    read_key = settings.MATIC_VIGIL_KEYS.READ_KEY
    params = {
        'msg': msg,
        'sig': sig,
        'key': key,
        'readKey': read_key,
        'showAllContracts': True
    }

    resp = helper_functions.make_post_call(
        url=settings.LOGIN_ENDPOINT,
        params=params
    )

    if resp is None:
        raise FailedRequestToMaticVigil("Failed request to /login endpoint")

    return resp


@handle_failed_maticvigil_exception
@retry(
    wait=wait_exponential(min=2, max=18, multiplier=1),
    stop=stop_after_attempt(2),
    retry=retry_if_exception(FailedRequestToMaticVigil),
    reraise=True
)
def update_hook_event(contract_address: int, hook_id: int, events: list):
    """
    This function will be used to activate hook events
    """
    verify_logger = logging.getLogger(__name__)
    verify_logger.setLevel(logging.DEBUG)
    socket_log_handler = logging.handlers.SocketHandler('localhost', logging.handlers.DEFAULT_TCP_LOGGING_PORT)
    verify_logger.addHandler(socket_log_handler)

    msg = "Check Contract through MaticVigil"
    private_key = settings.MATIC_VIGIL_KEYS.PRIVATE_KEY
    hash_msg = encode_defunct(text=msg)
    sig = Account.sign_message(hash_msg, private_key).signature.hex()
    key = settings.MATIC_VIGIL_KEYS.API_KEY
    read_key = settings.MATIC_VIGIL_KEYS.READ_KEY
    params = {
        'msg': msg,
        'sig': sig,
        'contract': contract_address,
        'key': key,
        'readKey': read_key,
        'id': hook_id,
        'type': "web",
        'events': events
    }

    resp = helper_functions.make_post_call(
        url=settings.UPDATE_HOOK_EVENTS_ENDPOINT,
        params=params
    )
    verify_logger.debug(resp)

    if resp is None:
        raise FailedRequestToMaticVigil("Failed request to /hooks/updateEvents endpoint")

    return resp


@retry(
    wait=wait_exponential(min=2, max=18, multiplier=1),
    stop=stop_after_attempt(6),
    retry=retry_if_exception(FailedRequestToMaticVigil)
)
async def deactivate_hook_event(hook_id: int, contract_address: str, session: aiohttp.ClientSession):
    """
    This function will be used to deactivate hook events
    """
    msg = "Check Contract through MaticVigil"
    private_key = settings.MATIC_VIGIL_KEYS.PRIVATE_KEY
    hash_msg = encode_defunct(text=msg)
    sig = Account.sign_message(hash_msg, private_key).signature.hex()
    key = settings.MATIC_VIGIL_KEYS.API_KEY
    read_key = settings.MATIC_VIGIL_KEYS.READ_KEY
    params = {
        'msg': msg,
        'sig': sig,
        'contract': contract_address,
        'key': key,
        'readKey': read_key,
        'id': hook_id,
        'type': "web",
    }

    resp = await helper_functions.make_post_call_async(
        url=settings.DEACTIVATE_HOOK_ENDPOINT,
        params=params,
        session=session
    )

    if resp == -1:
        raise FailedRequestToMaticVigil("Failed request to /hooks/deactivate endpoint")

    return resp


@retry(
    wait=wait_exponential(min=2, max=18, multiplier=1),
    stop=stop_after_attempt(6),
    retry=retry_if_exception(FailedRequestToMaticVigil)
)
async def activate_hook_event(contract_address: str, hook_id: int, session: aiohttp.ClientSession):
    """
    This function will be used to activate hook events
    """
    msg = "Check Contract through MaticVigil"
    private_key = settings.MATIC_VIGIL_KEYS.PRIVATE_KEY
    hash_msg = encode_defunct(text=msg)
    sig = Account.sign_message(hash_msg, private_key).signature.hex()
    key = settings.MATIC_VIGIL_KEYS.API_KEY
    read_key = settings.MATIC_VIGIL_KEYS.READ_KEY
    params = {
        'msg': msg,
        'sig': sig,
        'contract': contract_address,
        'key': key,
        'readKey': read_key,
        'id': hook_id,
        'type': "web",
    }

    resp = await helper_functions.make_post_call_async(
        url=settings.ACTIVATE_HOOK_ENDPOINT,
        params=params,
        session=session
    )

    if resp == -1:
        raise FailedRequestToMaticVigil("Failed request to /hooks/activate endpoint")

    return resp


@retry(
    wait=wait_exponential(min=2, max=18, multiplier=1),
    stop=stop_after_attempt(2),
    retry=retry_if_exception(FailedRequestToMaticVigil)
)
def add_hook_endpoint(contract_address: str, url: str):
    """
    This function will add a hook to the contract address
    """
    msg = "Check Contract through MaticVigil"
    private_key = settings.MATIC_VIGIL_KEYS.PRIVATE_KEY
    hash_msg = encode_defunct(text=msg)
    sig = Account.sign_message(hash_msg, private_key).signature.hex()
    key = settings.MATIC_VIGIL_KEYS.API_KEY
    read_key = settings.MATIC_VIGIL_KEYS.READ_KEY
    params = {
        'msg': msg,
        'sig': sig,
        'contract': contract_address,
        'key': key,
        'readKey': read_key,
        'type': "web",
        'web': url
    }

    resp = helper_functions.make_post_call(
        url=settings.ADD_HOOK_ENDPOINT,
        params=params
    )

    if resp is None:
        raise FailedRequestToMaticVigil("Failed request to /hooks/add endpoint")

    return resp


@retry(
    wait=wait_exponential(min=2, max=18, multiplier=1),
    stop=stop_after_attempt(6),
    retry=retry_if_exception(FailedRequestToMaticVigil)
)
def check_contract(contract_address: str):
    """
    This function will check if the contract exists and return the response to checkContract endpoint
    """
    msg = "Check Contract through MaticVigil"
    private_key = settings.MATIC_VIGIL_KEYS.PRIVATE_KEY
    hash_msg = encode_defunct(text=msg)
    sig = Account.sign_message(hash_msg, private_key).signature.hex()
    key = settings.MATIC_VIGIL_KEYS.API_KEY
    read_key = settings.MATIC_VIGIL_KEYS.READ_KEY
    params = {
        'msg': msg,
        'sig': sig,
        'contractAddress': contract_address,
        'key': key,
        'readKey': read_key
    }

    resp = helper_functions.make_post_call(
        url=settings.CHECK_CONTRACT_ENDPOINT,
        params=params
    )

    if resp is None:
        raise FailedRequestToMaticVigil("Failed request to /checkContract endpoint")

    return resp


@retry(
    wait=wait_exponential(min=2, max=18, multiplier=1),
    stop=stop_after_attempt(2),
    retry=retry_if_exception(FailedRequestToMaticVigil)
)
def add_contract(contract_address: str):
    """
    This function will just add the contract which has already been verified
    """
    msg = "Add Contract through MaticVigil"
    private_key = settings.MATIC_VIGIL_KEYS.PRIVATE_KEY
    hash_msg = encode_defunct(text=msg)
    sig = Account.sign_message(hash_msg, private_key).signature.hex()
    key = settings.MATIC_VIGIL_KEYS.API_KEY
    read_key = settings.MATIC_VIGIL_KEYS.READ_KEY
    skip_compiling = True
    params = {
        'msg': msg,
        'sig': sig,
        'key': key,
        'readKey': read_key,
        'skipCompiling': skip_compiling,
        'contractAddress': contract_address
    }

    resp = helper_functions.make_post_call(
        url=settings.VERIFY_CONTRACT_ENDPOINT,
        params=params
    )

    if resp is None:
        raise FailedRequestToMaticVigil("Failed request to /verify endpoint")

    return resp


@retry(
    wait=wait_exponential(min=2, max=18, multiplier=1),
    stop=stop_after_attempt(2),
    retry=retry_if_exception(FailedRequestToMaticVigil)
)
def verify_abi(contract_address: str, market_slug: str):
    """
    This function will verify the contract using the FixedProductMarketMaker abi
    """
    msg = "Verify Contract ABI through MaticVigil"
    private_key = settings.MATIC_VIGIL_KEYS.PRIVATE_KEY
    hash_msg = encode_defunct(text=msg)
    sig = Account.sign_message(hash_msg, private_key).signature.hex()
    key = settings.MATIC_VIGIL_KEYS.API_KEY
    read_key = settings.MATIC_VIGIL_KEYS.READ_KEY
    name = "FixedProductMarketMaker-" + '-'.join(market_slug.split('-')[2:5])
    skip_compiling = True
    version = "v0.6.5"
    optimization = True
    code = open('fpmm_abi.json', 'r').read()

    params = {
        'msg': msg,
        'sig': sig,
        'contractAddress': contract_address,
        'skipCompiling': skip_compiling,
        'name': name,
        'optimization': optimization,
        'version': version,
        'key': key,
        'readKey': read_key,
        'code': code
    }

    resp = helper_functions.make_post_call(
        url=settings.VERIFY_ABI_ENDPOINT,
        params=params,
    )
    # logging.error('Got verify response: %s', resp.text)
    if resp is None:
        raise FailedRequestToMaticVigil("Failed request to /verifyABI endpoint")
    return resp


@handle_failed_maticvigil_exception
@acquire_threading_semaphore
def verify_single_market(market, login_response, semaphore):
    """
    Verify the contract for a single market
    """
    verify_logger = logging.getLogger(__name__)
    verify_logger.setLevel(logging.DEBUG)
    socket_log_handler = logging.handlers.SocketHandler('localhost', logging.handlers.DEFAULT_TCP_LOGGING_PORT)
    verify_logger.addHandler(socket_log_handler)

    market_maker_contract_address = market['marketMakerAddress'].lower()
    verify_logger.debug("Verifying contract for market ID %s and marketMaker contract %s", market['id'], market_maker_contract_address)

    # The _contract_verified_flag can have three values:
    # 0: Contract was already added
    # 1: Contract has been verified and added now
    # -1: There was an error while verifying the Contract
    _contract_verified_flag = -1
    if login_response['success'] is True:
        my_contracts = [o['address'] for o in login_response['data']['contracts']]
        if market_maker_contract_address in my_contracts:
            verify_logger.debug("Skipping the verification of contract: " + market_maker_contract_address
                                + ", as it already has been added in the contract list")
            _contract_verified_flag = 0
        else:
            verify_logger.debug("Contract " + market_maker_contract_address + " has not been added yet")

    if _contract_verified_flag == -1:
        try:
            response_json = check_contract(market_maker_contract_address)
        except FailedRequestToMaticVigil:
            raise
        if response_json['success']:
            # Check if the contract has already been verified
            if response_json['found'] is None:
                verify_logger.debug("Contract %s has not been verified before", market_maker_contract_address)

                # Verify the contract through ABI
                verify_logger.debug("Verifying the contract through ABI")
                try:
                    abi_response = verify_abi(market_maker_contract_address, market.get('slug'))
                except FailedRequestToMaticVigil:
                    raise
                if abi_response['success'] and \
                        (abi_response['data']['contract'] == market_maker_contract_address):
                    verify_logger.debug("Contract verification %s for marketID %s was successful!", market_maker_contract_address, market['id'])
                    _contract_verified_flag = 1
                else:
                    verify_logger.debug("Contract verification %s for marketID %s was unsuccessful!", market_maker_contract_address, market['id'])
                    _contract_verified_flag = -1
            else:
                contract_name = response_json['found']
                # verify_logger.debug("Contract has been verified before: ")
                verify_logger.debug("Contract %s for marketID %s done already seen by MaticVigil %s", market_maker_contract_address, market['id'], contract_name)

                # Now just verify the contract
                try:
                    add_response = add_contract(market_maker_contract_address)
                except FailedRequestToMaticVigil:
                    raise
                if add_response['success'] and \
                        (add_response['data']['contract'] == market_maker_contract_address):
                    verify_logger.debug("Contract added %s for marketID %s successfully to MaticVigil account!",
                                        market_maker_contract_address, market['id'])
                    verify_logger.debug("The contract has been added successfully!")
                    _contract_verified_flag = 1
                else:
                    verify_logger.debug("Failed to add contract %s for marketID %s to MaticVigil account",
                                        market_maker_contract_address, market['id'])
                    _contract_verified_flag = -1
    return {
        'address': market_maker_contract_address,
        'success': _contract_verified_flag,
        'condition_id': market['conditionId'],
        'outcomes_num': len(market['outcomes']),
        'marketId': market['id']
    }


@provide_redis_conn
def verify_all_market_contracts(redis_conn: Redis = None):
    """
    This function will get all the markets from the strapi and then for each market get the
    marketAddress then verify them.
    """
    verify_logger = logging.getLogger(__name__)
    verify_logger.setLevel(logging.DEBUG)
    socket_log_handler = logging.handlers.SocketHandler('localhost', logging.handlers.DEFAULT_TCP_LOGGING_PORT)
    verify_logger.addHandler(socket_log_handler)

    # First get all the markets from the strapi_api:
    setproctitle.setproctitle('PowerLoom|MarketMakerProcessor|Worker')
    try:
        response_data = requests.get(settings.POLYMARKET_STRAPI_URL)
    except:
        return None
    else:
        response_data = response_data.json()
    if response_data:
        if not os.path.exists('static/cached_markets.json'):
            old_market_data = None
        else:
            with open('static/cached_markets.json', 'r') as fp:
                old_market_data = json.load(fp)
        cache_markets_data(old_market_data, response_data)
    else:
        return None
    polymarket_hook_id_key = "polymarketWebhook:hookId"
    hook_id = redis_conn.get(polymarket_hook_id_key)
    task_results = []
    if (hook_id is None) or (settings.FORCE_ADD_NEW_HOOK_ID is True):
        hook_add_resp = add_hook_endpoint(
            response_data[0]['marketMakerAddress'].lower(),
            urljoin(settings.WEBHOOK_LISTENER.ROOT, settings.WEBHOOK_LISTENER.MARKET_EVENT_LISTENER_PATH)
        )
        if hook_add_resp['success']:
            hook_id = hook_add_resp['data']['id']
            verify_logger.debug("Got the Hook id: ")
            verify_logger.debug(hook_id)
            _ = redis_conn.set(polymarket_hook_id_key, hook_id)
        else:
            verify_logger.warning("Failed to add new hook id")
            return None
    else:
        hook_id = int(hook_id)
        verify_logger.debug("Got the hook id from redis: ")
        verify_logger.debug(hook_id)

    sem = threading.BoundedSemaphore(settings.SNAPSHOT_MATICVIGIL_LIMITS.MAX_WORKERS)
    to_be_hook_registered_contracts = list()
    pending_liq_seeding = dict()
    pending_trade_vol_seeding = dict()
    try:
        login_response = login()
    except FailedRequestToMaticVigil:
        raise
    with BoundedThreadPoolExecutor(max_workers=settings.SNAPSHOT_MAX_WORKERS) as executor:
        future_to_rpcresult = {executor.submit(
            verify_single_market,
            market=each_market,
            login_response=login_response,
            semaphore=sem
        ): each_market for each_market in response_data}
    for future in as_completed(future_to_rpcresult):
        verify_logger.debug("=" * 80)
        single_market = future_to_rpcresult[future]
        try:
            rj = future.result()
        except Exception as exc:
            # do something in future
            verify_logger.error(
                'Error verifying contract %s against market %s on MaticVigil',
                single_market.get('marketMakerAddress'),
                single_market.get('id')
            )
            verify_logger.error(exc, exc_info=True)
            continue
        else:
            if rj['success'] == 1 or settings.FORCE_HOOK_ADD is True:
                verify_logger.debug('Scheduling task to register new hook against marketmaker contract %s', rj['address'])
                # verify_logger.debug(dict(
                #     contract_address=rj['address'],
                #     hook_id=hook_id,
                #     events=['FPMMBuy', 'FPMMSell', 'FPMMFundingAdded', 'FPMMFundingRemoved']
                # ))
                to_be_hook_registered_contracts.append(rj['address'])
            else:
                msg = f"Skipping hook ID update for contract: {rj['address']}"
                verify_logger.debug(msg)
            # set seed values for trade volume, liquidity, outcome prices
            if rj['success'] == 1 or settings.FORCE_SEED_LIQUIDITY is True:
                verify_logger.debug(
                    'Scheduling task to seed liquidity values and share prices against marketmaker contract %s',
                    rj['address']
                )
                pending_liq_seeding[rj['address']] = rj
            else:
                msg = f"Skipping seeding of liquidity values and share prices for contract: {rj['address']}"
                verify_logger.debug(msg)

            if rj['success'] == 1 or settings.FORCE_SEED_TRADE_VOLUME is True:
                verify_logger.debug(
                    'Scheduling task to seed trade volume against marketmaker contract %s',
                    rj['address']
                )
                pending_trade_vol_seeding[rj['address']] = rj

            else:
                msg = f"Skipping seeding of trade volume for contract: {rj['address']}"
                verify_logger.debug(msg)
        verify_logger.debug("=" * 80)

    # register hook ID against contract events
    with BoundedThreadPoolExecutor(max_workers=settings.SNAPSHOT_MAX_WORKERS) as executor:
        future_to_hook_add_result = {executor.submit(
            update_hook_event,
            contract_address=addr,
            hook_id=hook_id,
            events=['FPMMBuy', 'FPMMSell', 'FPMMFundingAdded', 'FPMMFundingRemoved']
        ): addr for addr in to_be_hook_registered_contracts}
    for future in as_completed(future_to_hook_add_result):
        verify_logger.debug("=" * 80)
        contract_address = future_to_hook_add_result[future]
        try:
            rj = future.result()
        except Exception as exc:
            # do something in future
            verify_logger.error(
                'Error adding hook ID %s against contract %s on MaticVigil',
                hook_id,
                contract_address
            )
            verify_logger.error(exc, exc_info=True)
            continue
        else:
            # task_results.append(rj)
            if rj['success']:
                verify_logger.debug(
                    'Successfully added hook ID %s against contract %s',
                    hook_id,
                    contract_address
                )
            else:
                verify_logger.error(
                    'Failed to add hook ID %s against contract %s on MaticVigil. Response follows:',
                    hook_id,
                    contract_address
                )
                verify_logger.error(rj)
    verify_logger.debug("All markets have been processed")


def main():
    setproctitle.setproctitle('PowerLoom|MarketMakerProcessor|Main')
    worker = None
    # asys = ActorSystem('multiprocTCPBase', logDefs=logcfg_thespian_main)
    while True:
        if not worker:
            worker = Process(target=verify_all_market_contracts)
            worker.start()
        else:
            p = psutil.Process(pid=worker.pid)
            if p.status() != psutil.STATUS_RUNNING:
                worker = None
                continue
        time.sleep(settings.TRADE_VOL_SNAPSHOT_INTERVAL)

