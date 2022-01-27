from web3 import Web3, WebsocketProvider, HTTPProvider
from exceptions import SelfExitException
from cached_property import cached_property as cached_property_async
from typing import Union
from eth_account.messages import encode_defunct
from eth_account.account import Account
from eth_utils import keccak
from functools import wraps, reduce
from dynaconf import settings
from redis_conn import provide_redis_conn, provide_redis_conn_insta, provide_async_redis_conn_insta, REDIS_CONN_CONF
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception, RetryCallState
from proto_system_logging import config_logger_with_namespace
from uuid import uuid4
from redis_keys import polymarket_base_trade_vol_key_f, position_id_cache_key_prefix_f
from message_models import PolymarketTradeVolumeBase, PolymarketLiquidityBase
import redis
import psutil
import os
import aioredis
import asyncio
import aiohttp
import logging
import logging.handlers
import sys
import eth_abi
import json
import time
import requests

""" Initialize the loggers """
# logging = logging.getLogger('PowerLoom|Helpers')
# logging.addHandler(logging.handlers.SocketHandler(**{
#     'host': 'localhost', 'port': logging.handlers.DEFAULT_TCP_LOGGING_PORT
# }))
# logging.setLevel(logging.DEBUG)
# logging.debug('Got powerloom helpers library logger')

conditional_token_contract_addr = '0x4d97dcd97ec945f40cf65f87097ace5ea0476045'

collateral_token_address = '0x2791bca1f2de4661ed88a30c99a7a9449aa84174'

w3 = Web3(HTTPProvider(settings.RPC.MATIC[0]))

with open('ctoken_abi.json', 'r') as f:
    ctoken_abi = f.read()

conditonal_token_contract_w3 = w3.eth.contract(address=w3.toChecksumAddress(conditional_token_contract_addr),
                                               abi=ctoken_abi)


def construct_kazoo_url(
        user=settings.ZOOKEEPER['user'],
        password=settings.ZOOKEEPER['password'],
        host=settings.ZOOKEEPER['host'],
        port=settings.ZOOKEEPER['port']
):
    if user and password:
        seg_1 = f'{user}:{password}@'
    else:
        seg_1 = ''
    if host and port:
        seg_2 = f'{host}:{port}'
    else:
        seg_2 = '127.0.0.1:2181'
    return f'{seg_1}{seg_2}'


class FailedRequestToMaticVigil(Exception):
    pass


class AsyncHTTPSessionCache:
    @cached_property_async
    async def get_aiohttp_cache(self) -> aiohttp.ClientSession:
        basic_rpc_connector = aiohttp.TCPConnector(limit=settings['rlimit']['file_descriptors'])
        aiohttp_client_basic_rpc_session = aiohttp.ClientSession(
            connector=basic_rpc_connector
        )
        return aiohttp_client_basic_rpc_session


def make_post_call(url: str, params: dict):
    try:
        logging.debug('Making post call to %s: %s', url, params)
        response = requests.post(url, json=params)
        if response.status_code == 200:
            return response.json()
        else:
            msg = f"Failed to make request {params}. Got status response from {url}: {response.status_code}"
            return None
    except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError
    ) as terr:
        logging.debug("Error occurred while making the post call.")
        logging.error(terr, exc_info=True)
        return None


class RPCException(Exception):
    def __init__(self, request, response, underlying_exception, extra_info):
        self.request = request
        self.response = response
        self.underlying_exception: Exception = underlying_exception
        self.extra_info = extra_info

    def __str__(self):
        ret = {
            'request': self.request,
            'response': self.response,
            'extra_info': self.extra_info,
            'exception': None
        }
        if isinstance(self.underlying_exception, Exception):
            ret.update({'exception': self.underlying_exception.__str__()})
        return json.dumps(ret)

    def __repr__(self):
        return self.__str__()


# TODO: support basic failover and/or load balanced calls that use the list of URLs. Introduce in rpc_helper.py
async def make_post_call_async(url: str, params: dict, session: aiohttp.ClientSession, tag: int):
    try:
        message = f"Making async post call to {url}: {params}"
        logging.debug(message)
        response_status_code = None
        response = None
        # per request timeout instead of configuring a client session wide timeout
        # from reported issue https://github.com/aio-libs/aiohttp/issues/3203
        async with session.post(url=url, json=params, timeout=aiohttp.ClientTimeout(
                total=None,
                sock_read=settings.TIMEOUTS.ARCHIVAL,
                sock_connect=settings.TIMEOUTS.CONNECTION_INIT
        )) as response_obj:
            response = await response_obj.json()
            response_status_code = response_obj.status
        if response_status_code == 200 and type(response) is dict:
            response.update({'tag': tag})
            return response
        else:
            msg = f"Failed to make request {params}. Got status response from {url}: {response_status_code}"
            logging.error(msg)
            raise RPCException(request=params, response=response, underlying_exception=None,
                               extra_info={'msg': msg, 'tag': tag})
    except aiohttp.ClientResponseError as terr:
        msg = 'aiohttp error occurred while making async post call'
        logging.debug(msg)
        logging.error(terr, exc_info=True)
        raise RPCException(request=params, response=response, underlying_exception=terr,
                           extra_info={'msg': msg, 'tag': tag})
    except Exception as e:
        msg = 'Exception occurred while making async post call'
        logging.debug(msg)
        logging.error(e, exc_info=True)
        raise RPCException(request=params, response=response, underlying_exception=e,
                           extra_info={'msg': msg, 'tag': tag})


def handle_failed_maticvigil_exception(fn):
    @wraps(fn)
    # TODO: generalize wrapper for adding context like contract address, when necessary
    def maticvigil_exception_wrapper(*args, **kwargs):
        try:
            contract_address = kwargs['market']['marketMakerAddress'].lower()
        except KeyError:
            contract_address = None
        try:
            out = fn(*args, **kwargs)
        except FailedRequestToMaticVigil as ferr:
            logging.error(ferr, exc_info=True)
            return {'address': contract_address, 'success': -1}
        except Exception as err:
            logging.warning("Some error occurred while making API call to MaticVigil")
            logging.error(err, exc_info=True)
            return {'address': contract_address, 'success': -1}
        else:
            return out

    return maticvigil_exception_wrapper


def cleanup_children_procs(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            fn(*args, **kwargs)
        except (SelfExitException, Exception) as e:
            if not isinstance(e, SelfExitException):
                logging.error(e, exc_info=True)
            logging.error('Initiating kill children...')
            # silently kill all children
            procs = psutil.Process().children()
            for p in procs:
                p.terminate()
            gone, alive = psutil.wait_procs(procs, timeout=3)
            for p in alive:
                p.kill()
        finally:
            return None

    return wrapper


def acquire_threading_semaphore(fn):
    @wraps(fn)
    def semaphore_wrapper(*args, **kwargs):
        semaphore = kwargs['semaphore']

        logging.debug("Acquiring threading semaphore")
        semaphore.acquire()
        try:
            resp = fn(*args, **kwargs)
        except Exception as e:
            raise
        finally:
            semaphore.release()

        return resp

    return semaphore_wrapper


@provide_redis_conn_insta
def acquire_maticivigil_rpc_semaphore(app_id=settings.RPC.MATIC[0].split('/')[-1], redis_conn: redis.Redis = None):
    p = redis_conn.pipeline()
    identifier = str(uuid4())
    now = time.time()
    semaphore_name = f'{app_id}:maticivigil:rpcSemaphore'
    logging.info('About to acquire RPC semaphore via zset %s', semaphore_name)
    # cleanout stagnant entries older than 60 seconds
    p.zremrangebyscore(semaphore_name, '-inf', now - 60)
    # logging.info('Removed old acquisition entries for RPC semaphore via zset %s', semaphore_name)
    p.zadd(semaphore_name, {identifier: now})
    # logging.info('Added new identifier for acquisition request %s in RPC semaphore via zset %s', identifier, semaphore_name)
    p.zrank(semaphore_name, identifier)
    # logging.info('Getting rank of new identifier %s for acquisition request in RPC semaphore via zset %s', identifier, semaphore_name)
    result = p.execute()
    logging.debug('Pipeline results in acquiring RPC semaphore via zset %s', result)
    if result[-1] < settings.SNAPSHOT_MAX_WORKERS:
        return identifier
    else:
        redis_conn.zrem(semaphore_name, identifier)
        return None


@provide_async_redis_conn_insta
async def acquire_maticivigil_rpc_semaphore_async(app_id=settings.RPC.MATIC[0].split('/')[-1],
                                                  redis_conn: aioredis.Redis = None):
    cmds_gather = list()
    # p = redis_conn.pipeline()
    identifier = str(uuid4())
    now = time.time()
    semaphore_name = f'{app_id}:maticivigil:rpcSemaphore'
    logging.info('About to acquire RPC semaphore via zset %s', semaphore_name)
    # cleanout stagnant entries older than 60 seconds
    cmds_gather.append(redis_conn.zremrangebyscore(key=semaphore_name, max=now - 60))
    cmds_gather.append(redis_conn.zadd(semaphore_name, now, identifier))
    cmds_gather.append(redis_conn.zrank(semaphore_name, identifier))
    # result = await p.execute()
    result = await asyncio.gather(*cmds_gather)
    logging.debug('Pipeline results in acquiring RPC semaphore via zset %s', result)
    if result[-1] < settings.SNAPSHOT_MAX_WORKERS:
        return identifier
    else:
        redis_conn.zrem(semaphore_name, identifier)
        return None


@provide_redis_conn_insta
def release_maticivigil_rpc_semaphore(identifier, app_id=settings.RPC.MATIC[0].split('/')[-1],
                                      redis_conn: redis.Redis = None):
    semaphore_name = f'{app_id}:maticivigil:rpcSemaphore'
    return redis_conn.zrem(semaphore_name, identifier)


@provide_async_redis_conn_insta
async def release_maticivigil_rpc_semaphore_async(identifier, app_id=settings.RPC.MATIC[0].split('/')[-1],
                                                  redis_conn: aioredis.Redis = None):
    semaphore_name = f'{app_id}:maticivigil:rpcSemaphore'
    return await redis_conn.zrem(semaphore_name, identifier)


def get_all_markets():
    response = requests.get(settings.POLYMARKET_STRAPI_URL)
    try:
        response.raise_for_status()
    except:
        response_data = None
    else:
        try:
            response_data = response.json()
        except:
            response_data = None
    return response_data


def process_marketmaker_contracts():
    all_markets = get_all_markets()


@provide_async_redis_conn_insta
async def append_cached_outcome_balances_liquidity(
        contract_address: str,
        event: dict,
        market_info: dict,
        _calling_timestamp: int,
        redis_conn: aioredis.Redis = None
):
    last_liquidity_cached_key = f'polymarket:marketMaker:{contract_address.lower()}:lastLiquidityCaching'
    last_liquidity_cached_marker = await redis_conn.get(last_liquidity_cached_key)
    if last_liquidity_cached_marker:
        cached_liquidity_key = f"cachedLiquidity:{contract_address}"
        cached_liquidity = await redis_conn.get(cached_liquidity_key)
        if cached_liquidity:
            cached_liquidity = json.loads(cached_liquidity)
        else:
            return
    else:
        return
    funding_sum = list()
    if event['event_name'] == 'FPMMFundingAdded':
        logging.debug('Funds added across all outcomes:')
        logging.debug(event['event_data']['amountsAdded'])
        funding_sum = event['event_data']['amountsAdded']
        logging.debug('Sum of funds added across all outcome positions to liquidity...')
    elif event['event_name'] == 'FPMMFundingRemoved':
        logging.debug('Funds removed across all outcomes:')
        logging.debug(event['event_data']['amountsRemoved'])
        funding_sum = list(map(lambda x: x * -1, event['event_data']['amountsRemoved']))
        logging.debug('Sum of funds removed across all outcome positions to liquidity...')
    logging.debug(funding_sum)
    outcome_num = len(market_info['outcomes'])
    outcome_balances = cached_liquidity['outcomeBalances']
    for i in range(outcome_num):
        outcome_balances[i] += funding_sum[i]
    legit_outcomes_num = 0
    final_product = 1
    for _ in outcome_balances:
        if _ != 0:
            legit_outcomes_num += 1
            final_product *= _
    if legit_outcomes_num != 0:
        final_liquidity = pow(final_product, 1 / legit_outcomes_num) / pow(10, 6)
        if type(final_liquidity) is complex:
            final_liquidity = 0
    else:
        final_liquidity = 0
    liquidity_data = {
        'chainHeight': event['blockNumber'],
        'liquidity': final_liquidity,
        'outcomeBalances': outcome_balances,
        'timestamp': _calling_timestamp
    }
    await redis_conn.set(cached_liquidity_key, json.dumps(liquidity_data))
    await redis_conn.set(last_liquidity_cached_key, str(event['blockNumber']))
    try:
        await cache_outcome_prices(
            contract_address=contract_address,
            outcome_balances=outcome_balances,
            final_product=final_product,
            redis_conn=redis_conn
        )
    except Exception as e:
        logging.error('Error caching outcome prices while appending new liquidity events to Redis')
        logging.error(e, exc_info=True)


@provide_async_redis_conn_insta
async def append_cached_trade_vol(
        contract_address: str,
        event: dict,
        _calling_timestamp: int,
        redis_conn: aioredis.Redis = None
):
    cached_trade_vol_key = f"cachedTradeVolume:{contract_address}"
    last_cached_marker_key = f'polymarket:marketMaker:{contract_address.lower()}:lastTradeVolCaching'
    last_cached_marker = await redis_conn.get(last_cached_marker_key)
    if last_cached_marker:
        cached_trade_vol = await redis_conn.get(cached_trade_vol_key)
        if cached_trade_vol:
            cached_trade_vol = json.loads(cached_trade_vol)
            logging.debug("Got cached trade vol so far from redis: ")
            logging.debug(cached_trade_vol)
        else:
            return
    else:
        return
    past_trade_vol = cached_trade_vol['tradeVolume']
    if event['event_name'] == 'FPMMBuy':
        logging.debug('Adding buy amounts to trade volume')
        logging.debug(event['event_data'])
        past_trade_vol += event['event_data']['investmentAmount'] / pow(10, 6)
    elif event['event_name'] == 'FPMMSell':
        logging.debug('Adding sell amounts to trade volume')
        logging.debug(event['event_data'])
        past_trade_vol += event['event_data']['returnAmount'] / pow(10, 6)
    logging.debug('Updated trade volume')
    json_trade_vol_data = {
        'tradeVolume': float(f"{past_trade_vol:.4f}"),
        'chainHeight': event['blockNumber'],
        'timestamp': _calling_timestamp
    }
    await redis_conn.set(cached_trade_vol_key, json.dumps(json_trade_vol_data))
    await redis_conn.set(last_cached_marker_key, str(event['blockNumber']))


@provide_async_redis_conn_insta
async def update_cached_outcome_balances_liquidity(
        contract_address: str,
        chain_height: int,
        market_info: dict,
        _calling_timestamp: int,
        redis_conn: aioredis.Redis = None
):
    """
    - Use the events in the cache to update the outcome balances and liquidity
    """
    last_liquidity_cached_key = f'polymarket:marketMaker:{contract_address.lower()}:lastLiquidityCaching'
    last_liquidity_cached_marker = await redis_conn.get(last_liquidity_cached_key)
    if last_liquidity_cached_marker:
        last_liquidity_cached_marker = int(last_liquidity_cached_marker)
        min_score = last_liquidity_cached_marker + 1
        cached_liquidity_key = f"cachedLiquidity:{contract_address}"
        cached_liquidity = await redis_conn.get(cached_liquidity_key)
        if cached_liquidity:
            cached_liquidity = json.loads(cached_liquidity)
        else:
            return
        logging.debug("Got cached liquidity so far from redis: ")
        logging.debug(cached_liquidity)
        outcome_balances = cached_liquidity['outcomeBalances']
    else:
        seeded_outcomes_liquidity = await seed_liquidity_data_async(
            contract_address=contract_address,
            chain_height=chain_height - 1,  # seed liquidity data up till event_seen_chain_height - 1
            condition_id=market_info.get('conditionId'),
            outcomes_num=len(market_info['outcomes']),
            market_id=market_info.get('id'),
            redis_conn=redis_conn
        )
        min_score = seeded_outcomes_liquidity['chainHeight'] + 1
        outcome_balances = seeded_outcomes_liquidity['outcomeBalances']
    if chain_height - (min_score - 1) < settings.EVENT_CONFIRMATION_BLOCK_HEIGHT:
        logging.debug('Not updating cached outcome balances and liquidity')
        logging.debug(
            {'contract': contract_address, 'chain_height': {'event': chain_height, 'last_cache': min_score - 1}})
        return
    else:
        logging.debug('Updating cached outcome balances and liquidity')
        logging.debug(
            {'contract': contract_address, 'chain_height': {'event': chain_height, 'last_cache': min_score - 1}})
    max_score = chain_height - settings.EVENT_CACHE_COLLECTION_CHAIN_HEAD_OFFSET
    # Get the events stored on redis
    outcome_num = len(market_info['outcomes'])

    # Retrieve the funding added amounts
    funding_added_key = f"{contract_address}:fundingAdded"
    out = await redis_conn.zrangebyscore(
        key=funding_added_key,
        max=max_score,
        min=min_score
    )
    if out:
        funding_added_events = list(map(lambda x: json.loads(x.decode('utf-8')), out))
        # amounts added is an array corresponding to funding added for each outcome index
        funding_added_amount = list(map(lambda x: x['event_data']['amountsAdded'], funding_added_events))
        total_funding_added_amount = []
        # only one event, adding a dummy funding added array of [0, 0,...0] to help with reduce()
        if len(funding_added_amount) == 1:
            funding_added_amount.append([0] * outcome_num)
        for i in range(outcome_num):
            _outcome_total_funding_added = reduce(lambda a, b: a + b, map(lambda x: x[i], funding_added_amount))
            total_funding_added_amount.append(_outcome_total_funding_added)

    else:
        total_funding_added_amount = [0] * len(outcome_balances)

    # current_timestamp = int(time.time())
    # Retrieve the funding removed amount
    funding_removed_key = f"{contract_address}:fundingRemoved"
    out = await redis_conn.zrangebyscore(
        key=funding_removed_key,
        max=max_score,
        min=min_score
    )
    if out:
        funding_removed_events = list(map(lambda x: json.loads(x.decode('utf-8')), out))
        funding_removed_amount = list(map(lambda x: x['event_data']['amountsRemoved'], funding_removed_events))
        total_funding_removed_amount = []
        if len(funding_removed_amount) == 1:
            funding_removed_amount.append([0] * outcome_num)
        for i in range(outcome_num):
            _outcome_total_funding_removed = reduce(lambda a, b: a + b, map(lambda x: x[i], funding_removed_amount))
            total_funding_removed_amount.append(_outcome_total_funding_removed)
    else:
        total_funding_removed_amount = [0] * len(outcome_balances)

    for i in range(outcome_num):
        outcome_balances[i] += total_funding_added_amount[i]
        outcome_balances[i] -= total_funding_removed_amount[i]
    # json_outcome_data = {'outcome_balances': outcome_balances, 'timestamp': _calling_timestamp}
    # out = await redis_conn.set(outcome_balances_cache_key, json.dumps(json_outcome_data))

    # Also update the liquidity
    final_product = 1
    _outcomes_num = 0
    for outcome_b in outcome_balances:
        if int(outcome_b) != 0:
            final_product *= int(outcome_b)
            _outcomes_num += 1
    if _outcomes_num != 0:
        final_liquidity = pow(final_product, 1 / _outcomes_num) / pow(10, 6)
        if type(final_liquidity) is complex:
            final_liquidity = 0
    else:
        final_liquidity = 0
    logging.debug({contract_address: {
        "outcome_balances": outcome_balances,
        "liquidity": final_liquidity
    }})

    cached_liquidity_key = f"cachedLiquidity:{contract_address}"
    liquidity_data = {
        'chainHeight': max_score,
        'liquidity': final_liquidity,
        'outcomeBalances': outcome_balances,
        'timestamp': _calling_timestamp
    }
    await redis_conn.set(cached_liquidity_key, json.dumps(liquidity_data))
    await redis_conn.set(last_liquidity_cached_marker, str(max_score))
    await cache_outcome_prices(
        contract_address=contract_address,
        outcome_balances=outcome_balances,
        final_product=final_product,
        redis_conn=redis_conn
    )


def get_market_data_by_address(contract_address: str):
    try:
        f_ = open('static/cached_markets.json', 'r')
        markets = json.loads(f_.read())
    except Exception as e:
        logging.error(e, exc_info=True)
    else:
        for market in markets:
            if market['marketMakerAddress'].lower() == contract_address.lower():
                return market
    return None


def get_market_data_by_id(market_id: int):
    try:
        with open('static/cached_markets.json', 'r') as f:
            local_markets_cached = json.load(f)
    except Exception as e:
        logging.error('Error loading cached markets json')
        return None
    contract_address = None
    for _ in local_markets_cached:
        if _.get('id') == market_id:
            contract_address = _.get('marketMakerAddress')
            break
    if not contract_address:
        logging.error(f'Could not find market information against market ID: {market_id}')
    return contract_address


def calculate_coll_pos_ids(outcome_index, condition_id, conditonal_token_contract):
    logging.debug('-' * 40)
    logging.debug('Calculating pool balances for outcome index')
    logging.debug(outcome_index)
    logging.debug('-' * 40)
    logging.debug('Getting collection IDs against condition ID')
    logging.debug(condition_id)

    collection_ids_res = conditonal_token_contract.getCollectionId(
        '0x' + '0' * 64,
        condition_id,
        str(outcome_index)
    )
    logging.debug(collection_ids_res)
    logging.debug('Getting position IDs against collection ID')
    logging.debug(collection_ids_res['data'][0]['bytes32'])
    position_id_res = conditonal_token_contract.getPositionId(
        collateral_token_address,
        collection_ids_res['data'][0]['bytes32']
    )
    logging.debug(position_id_res)
    logging.debug('Getting pool balance against position ID')
    logging.debug(position_id_res['data'][0]['uint256'])

    return collection_ids_res['data'][0]['bytes32'], str(position_id_res['data'][0]['uint256'])


def calculate_coll_pos_ids_w3(outcome_index, condition_id):
    logging.debug('-' * 40 + '\nCalculating pool balances for outcome index %s\n' + '-' * 40, outcome_index)
    collection_ids_res = conditonal_token_contract_w3.functions.getCollectionId(
        '0x' + '0' * 64,
        condition_id,
        outcome_index
    ).call()
    collection_id = '0x' + collection_ids_res.hex()
    logging.debug('Getting collection IDs against condition ID %s: %s', condition_id, collection_id)
    logging.debug('Getting position IDs against collection ID %s', collection_id)
    position_id_res = conditonal_token_contract_w3.functions.getPositionId(
        collateral_token_address,
        collection_id
    ).call()
    position_id = '0x' + position_id_res.hex()
    logging.debug('Got position ID against collection ID %s: %s', collection_id, position_id)

    return collection_id, position_id


@provide_async_redis_conn_insta
async def seed_liquidity_data_async(
        contract_address: str,
        chain_height: int,
        condition_id: str,
        outcomes_num: int,
        market_id: str,
        redis_conn: aioredis.Redis
) -> Union[PolymarketLiquidityBase, None]:
    """
        - Seed the initial liquidity data
    """
    # TODO: pass SDK object/instantiated contract object to helper functions to avoid multiple instantiation during imports
    # evc = EVCore(verbose=True)
    # conditonal_token_contract = evc.generate_contract_sdk(
    #     contract_address=conditional_token_contract_addr,
    #     app_name='ConditionalToken'
    # )
    market_maker_contract_address = contract_address
    # outcome_indices = filter(lambda x: x != 0 and x != pow(2, outcomes_num) - 1, range(0, outcomes_num + 1))
    outcome_indices = list()
    for i in range(0, outcomes_num):
        base_binary = 1
        base_binary = base_binary << i
        outcome_indices.append(base_binary)
    final_product = 1
    outcome_balances = list()
    _outcomes_num = 0
    position_id_cache_key_prefix = position_id_cache_key_prefix_f.format(market_id)

    _outcomes_num = 0
    for outcome_index in outcome_indices:
        position_id_cache_key = position_id_cache_key_prefix + str(outcome_index)
        r = await redis_conn.hgetall(position_id_cache_key)
        if not len(r):
            logging.debug('Did not find cached collection and position ID for liquidity seeding request: \n%s', {
                'marketMaker': market_maker_contract_address,
                'conditionID': condition_id,
                'outcomeIndex': outcome_index
            })
            collection_id, position_id = calculate_coll_pos_ids_w3(
                outcome_index, condition_id
            )
            logging.debug('Calculated collection and position ID for liquidity seeding request. Setting in redis.\n%s',
                          {
                              'marketMaker': market_maker_contract_address,
                              'conditionID': condition_id,
                              'outcomeIndex': outcome_index,
                              'collectionID': collection_id,
                              'positionID': position_id
                          })
            await redis_conn.hmset_dict(
                key=position_id_cache_key,
                **{
                    'collection_id': collection_id,
                    'position_id': position_id
                }
            )
        else:
            cached_outcome_data = {k.decode('utf-8'): v.decode('utf-8') for k, v in r.items()}
            collection_id = cached_outcome_data['collection_id']
            position_id = cached_outcome_data['position_id']
            logging.debug(
                'Found cached collection and position ID for following market in liquidity seeding request \n%s', {
                    'marketMaker': market_maker_contract_address,
                    'conditionID': condition_id,
                    'outcomeIndex': outcome_index,
                    'collectionID': collection_id,
                    'positionID': position_id
                })
        balances_res = conditonal_token_contract_w3.functions.balanceOf(
            market_maker_contract_address,
            str(position_id)
        ).call(block_identifier=chain_height)
        logging.debug(balances_res)
        if balances_res != 0:
            final_product *= balances_res
            _outcomes_num += 1
        outcome_balances.append(balances_res)

    logging.debug('Calculating final liquidity from all balances across positions in liquidity seeding request')
    if _outcomes_num != 0:
        final_liquidity = pow(final_product, 1 / _outcomes_num) / pow(10, 6)
        if type(final_liquidity) is complex:
            final_liquidity = 0
    else:
        final_liquidity = 0

    """ Calculate the outcome prices """
    if all(outcome_balances) == 0:
        prices = [0 for _ in range(outcomes_num)]
    else:
        logging.info('Calculating denominator in liquidity seeding request')
        denominator = reduce(lambda a, b: a + b, map(lambda x: final_product / x, outcome_balances))
        logging.info(denominator)
        prices = list(map(lambda x: (final_product / x) / denominator, outcome_balances))

    seed_liquidity_data: PolymarketLiquidityBase = PolymarketLiquidityBase(
        contract=contract_address,
        liquidity=final_liquidity,
        outcomeBalances=outcome_balances,
        prices=prices,
        chainHeight=chain_height,
        timestamp=f'{time.time(): .4f}'
    )
    return seed_liquidity_data




async def cache_outcome_prices(
        contract_address: str,
        outcome_balances,
        final_product,
        redis_conn: aioredis.Redis,
        _calling_timestamp: int,
):
    """
    Cache the outcome_prices
    """
    _outcome_balances = []
    for i, o_balance in enumerate(outcome_balances):
        if o_balance != 0:
            _outcome_balances.append(o_balance)

    logging.info('Calculating denominator')
    denominator = reduce(lambda a, b: a + b, map(lambda x: final_product / x, _outcome_balances))
    logging.info(denominator)
    prices = list(map(lambda x: (final_product / x) / denominator, _outcome_balances))
    _prices = []
    j = 0
    for i, o in enumerate(outcome_balances):
        if o == 0:
            _prices.append(0)
        else:
            _prices.append(prices[j])
            j = j + 1

    logging.info('Calculated outcome token prices for caching')
    logging.debug(_prices)
    cached_outcome_prices_key = f"cachedOutcomePrices:{contract_address}"
    await redis_conn.set(cached_outcome_prices_key, json.dumps(_prices))



def cache_markets_data(base_market_data, new_market_data):
    if base_market_data:
        base_market_data_dict = {each.get('id'): each for each in base_market_data}
        new_market_data_dict = {each.get('id'): each for each in new_market_data}
        for market_id in new_market_data_dict.keys():
            if market_id in base_market_data_dict.keys():
                try:
                    base_market_data_dict[market_id].update(new_market_data_dict[market_id])
                except:
                    pass
            else:
                base_market_data_dict[market_id] = new_market_data_dict[market_id]
        base_market_data = [v for v in base_market_data_dict.values()]
        with open('static/cached_markets.json', 'w') as f2:
            json.dump(base_market_data, f2)
    else:
        try:
            os.stat('./static')
        except:
            os.mkdir('./static')
        with open('static/cached_markets.json', 'w') as f2:
            json.dump(new_market_data, f2)


def get_event_name_from_sig(event_sig: str):
    if event_sig == get_event_sig("FPMMBuy"):
        return "FPMMBuy"
    elif event_sig == get_event_sig("FPMMSell"):
        return "FPMMSell"
    return -1


def get_event_params_from_sig(event_sig: str):
    indexed_params = {}
    unindexed_params = {}
    if event_sig == get_event_sig("FPMMBuy"):
        indexed_params = {
            'buyer': 'address',
            'outcomeIndex': 'uint256'
        }

        unindexed_params = {
            'investmentAmount': 'uint256',
            'feeAmount': 'uint256',
            'outcomeTokensBought': 'uint256'
        }
    elif event_sig == get_event_sig("FPMMSell"):
        indexed_params = {
            'seller': 'address',
            'outcomeIndex': 'uint256'
        }

        unindexed_params = {
            'returnAmount': 'uint256',
            'feeAmount': 'uint256',
            'outcomeTokensSold': 'uint256'
        }

    return indexed_params, unindexed_params


def get_event_sig(event_name: str):
    if event_name == "FPMMBuy":
        event_def = "FPMMBuy(address,uint256,uint256,uint256,uint256)"
    elif event_name == "FPMMSell":
        event_def = f"FPMMSell(address,uint256,uint256,uint256,uint256)"
    else:
        logging.debug("Unknow event_name passed: ")
        logging.debug(event_name)
        return -1

    event_sig = '0x' + keccak(text=event_def).hex()
    # logging.debug("Generated event sig: ")
    # logging.debug(event_sig)

    return event_sig


def maticvigil_login():
    """
        This function is used to get a list of all contracts
        """
    msg = "dummystr"
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

    resp = make_post_call(
        url=settings.LOGIN_ENDPOINT,
        params=params
    )

    if resp == -1:
        raise FailedRequestToMaticVigil("Failed request to /login endpoint")

    return resp


def before_get_logs_retry_sleep(retry_state: RetryCallState):
    logging.info('Logging try attempt %s on eth_getLogs: %s', retry_state.attempt_number, retry_state.kwargs)


@retry(
    wait=wait_exponential(min=2, max=15, multiplier=1),
    stop=stop_after_attempt(3),
    retry=retry_if_exception(FailedRequestToMaticVigil),
    before_sleep=before_get_logs_retry_sleep
)
def eth_get_logs(contract_address: str, events: list, from_block: int, to_block: int):
    """
        Function to get the logs for the given data
    """
    event_sigs = list(map(get_event_sig, events))
    logging.debug(event_sigs)
    if -1 in event_sigs:
        _bad_event_name = event_sigs[event_sigs.index(-1)]
        raise AssertionError(f"Unknown event_name passed: {_bad_event_name}")

    assert from_block < to_block, f"from_block:{from_block} should be less than to_block:{to_block}"

    from_block = hex(from_block)
    to_block = hex(to_block)

    rpc_json = {
        "jsonrpc": "2.0",
        "method": "eth_getLogs",
        "params": [
            {
                "topics": event_sigs,
                "toBlock": to_block,
                "fromBlock": from_block,
                "address": contract_address
            }
        ],
        "id": 74
    }
    resp_json = make_post_call(settings.RPC.MATIC[0], params=rpc_json)
    if resp_json is None:
        err_map = {"contract": contract_address, "events": events, "from_block": from_block, "to_block": to_block}
        logging.error(f"Failed to get logs | {json.dumps(err_map)}")
        raise FailedRequestToMaticVigil

    else:
        try:
            results = resp_json['result']
        except (TypeError, KeyError) as err:
            logging.debug("Got back an invalid response")
            logging.debug(resp_json)
            return None

    return results


async def eth_get_logs_async(
        contract_address: str,
        events: list,
        from_block: int, to_block: int,
        session: aiohttp.ClientSession
):
    """
        Function to get the logs for the given data
    """
    event_sigs = list(map(get_event_sig, events))
    logging.debug('Fetching logs for event topic: %s', event_sigs)
    if -1 in event_sigs:
        _bad_event_name = event_sigs[event_sigs.index(-1)]
        raise AssertionError(f"Unknown event_name passed: {_bad_event_name}")

    assert from_block < to_block, f"from_block:{from_block} should be less than to_block:{to_block}"
    query_range_batches = dict()
    idx = 1
    completed_status = dict()
    no_of_attempts = dict()
    final_logs = list()
    for begin_block in range(from_block, to_block, settings.RPC.LOGS_QUERY.CHUNK):
        from_block_query = hex(begin_block)
        if to_block - begin_block < settings.RPC.LOGS_QUERY.CHUNK:
            to_block_query = hex(to_block)
        else:
            to_block_query = hex(begin_block + settings.RPC.LOGS_QUERY.CHUNK - 1)
        query_range_batches.update({idx: (from_block_query, to_block_query)})
        completed_status.update({idx: False})
        no_of_attempts.update({idx: 0})
        logging.debug('Created query range for eth_getLogs: %s', query_range_batches[idx])
        idx += 1
    query_range_tasks = dict()
    for each_query_range_idx in query_range_batches.keys():
        each_query_range = query_range_batches[each_query_range_idx]
        logging.debug('Querying eth_getLogs for range %s', each_query_range)
        rpc_json = {
            "jsonrpc": "2.0",
            "method": "eth_getLogs",
            "params": [
                {
                    "topics": event_sigs,
                    "fromBlock": each_query_range[0],
                    "toBlock": each_query_range[1],
                    "address": contract_address
                }
            ],
            "id": 74
        }
        t = make_post_call_async(
            url=settings.RPC.MATIC[0],
            params=rpc_json,
            session=session,
            tag=each_query_range_idx
        )
        query_range_tasks.update({each_query_range_idx: t})
    while True:
        if not query_range_tasks or all(v >= settings.RPC.LOGS_QUERY.RETRY + 1 for v in no_of_attempts.values()):
            break
        rets = await asyncio.gather(*query_range_tasks.values(), return_exceptions=True)

        for result in rets:
            result_idx = 0
            if isinstance(result, RPCException):
                err_map = {
                    'contract': contract_address,
                    'request': result.request,
                    'response': result.response,
                    'underlying_exception': result.underlying_exception
                }
                logging.error("Failed to get logs | RPC Exception:\n%s", err_map)
                result_idx = result.extra_info['tag']
            elif type(result) is dict:
                result_idx = result['tag']
                if 'result' not in result.keys() or type(result['result']) is not list:
                    err_map = {
                        'contract': contract_address,
                        'request_query_range': query_range_batches[result_idx],
                        'response': result
                    }
                    logging.error("Failed to get logs | Returned result:\n%s", err_map)
                else:
                    final_logs.extend(result['result'])
                    logging.info('Got logs for contract %s in range %s', contract_address,
                                 query_range_batches[result_idx])
                    del query_range_tasks[result_idx]
            else:
                err_map = {
                    'contract': contract_address,
                    'request_query_range': query_range_batches[result_idx],
                    'response': result
                }
                logging.error("Failed to get logs | Returned result:\n%s", err_map)
            if result_idx != 0:
                no_of_attempts[result_idx] += 1
    if query_range_tasks:  # there are ranges still remaining to be fetched
        err_info = {"topics": event_sigs, "fromBlock": from_block, "toBlock": to_block, "address": contract_address}
        logging.error('Could not fetch all logs for %s | Request history: %s | Batches: %s',
                      err_info, no_of_attempts, query_range_batches)
        return None
    else:
        return final_logs


def decode_event_data(topics: list, data: str):
    """
        - Given the topic and data, decode the values and return back
        the parameters
    """
    assert len(topics) > 0, "Empty topic sent as a parameter"

    event_sig = topics[0]

    # Decode the indexed_params
    indexed_params, unindexed_params = get_event_params_from_sig(event_sig=event_sig)

    indexed_data = {}
    unindexed_data = {}

    for i in range(1, len(topics)):
        param_name = list(indexed_params.keys())[i - 1]
        indexed_data[param_name] = eth_abi.decode_single(
            typ=indexed_params[param_name],
            data=bytes.fromhex(topics[i][2:])
        )
    _data = eth_abi.decode_abi(
        types=unindexed_params.values(),
        data=bytes.fromhex(data[2:])
    )
    for i in range(len(_data)):
        param_name = list(unindexed_params.keys())[i]
        unindexed_data[param_name] = _data[i]

    final_data = {'event_sig': topics[0]}
    final_data.update(indexed_data)
    final_data.update(unindexed_data)

    return final_data


def parse_logs(result: list):
    """
        Given a list of logs, parse them
    """

    events = []
    for log in result:
        if 'topics' not in log.keys():
            logging.debug("Unknown log found. Skipping...")
            logging.debug(log)
            continue

        try:
            event_data = decode_event_data(
                topics=log['topics'],
                data=log['data']
            )
        except AssertionError as aerr:
            logging.debug("Empty topics log. Skipping...")
            logging.debug(log)
            continue

        block_num = int(log['blockNumber'], base=16)
        event_data['blockNumber'] = block_num
        events.append(event_data)

    return events


def eth_get_block_number():
    """
        Get the latest block number in the chain
    """

    json_rpc_params = {
        "jsonrpc": "2.0",
        "method": "eth_blockNumber",
        "params": [],
        "id": 83
    }

    resp = make_post_call(settings.RPC.MATIC[0], params=json_rpc_params)

    if resp is None:
        logging.warning("Failed to get the block number from the rpc call")
        return None

    try:
        hex_block_num = resp.get('result')
        block_num = int(hex_block_num, 16)
    except:
        return None
    else:
        return block_num


async def eth_get_block_number_async(session: aiohttp.ClientSession):
    """
        Get the latest block number in the chain
    """

    json_rpc_params = {
        "jsonrpc": "2.0",
        "method": "eth_blockNumber",
        "params": [],
        "id": 83
    }

    resp = await make_post_call_async(settings.RPC.MATIC[0], params=json_rpc_params)

    if resp is None:
        logging.warning("Failed to get the block number from the rpc call")
        return None

    try:
        hex_block_num = resp.get('result')
        block_num = int(hex_block_num, 16)
    except:
        return None
    else:
        return block_num
