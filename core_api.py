from typing import Optional, Union
from fastapi import Depends, FastAPI, Request, Response, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlencode, urljoin
from dynaconf import settings
import logging
import sys
import coloredlogs
import aioredis
import aiohttp
import json
import os
import time
from redis_conn import provide_async_redis_conn
from functools import reduce
from uniswap_functions import v2_pairs_data, read_json_file
from redis_keys import (
    uniswap_pair_contract_V2_pair_data
)
from web3 import Web3

REDIS_CONN_CONF = {
    "host": settings['redis']['host'],
    "port": settings['redis']['port'],
    "password": settings['redis']['password'],
    "db": settings['redis']['db']
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
    app.redis_pool = await aioredis.create_pool(
        address=(REDIS_CONN_CONF['host'], REDIS_CONN_CONF['port']),
        db=REDIS_CONN_CONF['db'],
        password=REDIS_CONN_CONF['password'],
        maxsize=100
    )


def check_onchain_param(onChain):
    on_chain = False
    if onChain.lower() == 'false':
        on_chain = False
    elif onChain.lower() == 'true':
        on_chain = True
    return on_chain


def project_namespace_inject(request: Request, stream: str = Query(default='pair_total_reserves')):
    """
        This dependency injection is meant to support multiple 'streams' of snapshots submitted to Audit Protocol core.
        for eg. pair total reserves, pair trades etc. Effectively, it injects namespaces into a project ID
    """
    pair_contract_address = request.path_params['pair_contract_address']
    audit_project_id = f'uniswap_pairContract_{stream}_{pair_contract_address}_{settings.NAMESPACE}'
    return audit_project_id


async def get_market_address(market_id: str, redis_conn: aioredis.Redis):
    market_id_key = f"marketId:{market_id}:contractAddress"
    out = await redis_conn.get(market_id_key)
    if out:
        return out.decode('utf-8')
    else:
        # Fetch the contract address from the file
        try:
            f_ = open(f"static/cached_markets.json", 'r')
        except Exception as e:
            rest_logger.warning("Unable to open the cached_markets.json file")
            rest_logger.error(e, exc_info=True)
        else:
            rest_logger.debug("Found cached_markets.json file")
            json_data = json.loads(f_.read())
            for market in json_data:
                if int(market['id']) == int(market_id):
                    out = await redis_conn.set(market_id_key, market['marketMakerAddress'].lower())
                    rest_logger.debug("Saved the following data to redis")
                    rest_logger.debug({"marketId": market_id, "contract_address": market['marketMakerAddress'].lower()})
                    return market['marketMakerAddress'].lower()
    return -1


def on_chain_param_check(onChain: str = Query(default='false')):
    return check_onchain_param(onChain)


@app.get('/stats')
async def get_stats(
        request: Request,
        response: Response
):
    redis_conn_raw = await request.app.redis_pool.acquire()
    redis_conn: aioredis.Redis = aioredis.Redis(redis_conn_raw)
    c = await redis_conn.get('polymarket:markets:stats')
    request.app.redis_pool.release(redis_conn_raw)
    if not c:
        return {
            'totalMarkets': 0,
            'totalSnapshots': {'onChain': 0, 'offChain': 0},
            'totalDiffs': {'onChain': 0, 'offChain': 0}
        }
    else:
        return json.loads(c)


@app.get('/diffs/latest')
async def get_latest_diffs(
        request: Request,
        maxCount: int = Query(default=20),
        on_chain: bool = Depends(on_chain_param_check)
):
    query_params = {'namespace': 'polymarket_onChain_' if on_chain else 'polymarket_offChain_', 'maxCount': maxCount}
    fetch_url = urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL, f'/projects/updates')
    async with aiohttp.ClientSession() as session:
        async with session.get(url=fetch_url, params=query_params) as resp:
            resp_json = await resp.json()
            for idx, each_market in enumerate(resp_json.copy()):
                audit_project_id = each_market['projectId']
                each_market['id'] = audit_project_id.split('_')[2]
                resp_json[idx] = each_market
            return resp_json


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
    redis_conn_raw = await request.app.redis_pool.acquire()
    redis_conn: aioredis.Redis = aioredis.Redis(redis_conn_raw)
    request_info_data = {
        'maxCount': max_count,
        'fromHeight': from_height,
        'toHeight': to_height,
        'data': data,
        'projectId': project_id
    }
    request_info_json = json.dumps(request_info_data)
    _ = await redis_conn.set(request_info_key, request_info_json)
    request.app.redis_pool.release(redis_conn_raw)


async def delete_request_data(
        request: Request,
        request_id: str
):
    request_info_key = f"pendingRequestInfo:{request_id}"
    redis_conn_raw = await request.app.redis_pool.acquire()
    redis_conn: aioredis.Redis = aioredis.Redis(redis_conn_raw)

    # Delete the request info data
    _ = await redis_conn.delete(key=request_info_key)

    request.app.redis_pool.release(redis_conn_raw)


@app.get('/snapshots/{pair_contract_address:str}')
async def get_past_snapshots(
        request: Request,
        response: Response,
        maxCount: Optional[int] = Query(None),
        audit_project_id: str = Depends(project_namespace_inject),
        data: Optional[str] = Query('false')
):
    last_block_height_url = urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL, f'/{audit_project_id}/payloads/height')
    async with aiohttp.ClientSession() as session:
        async with session.get(url=last_block_height_url) as resp:
            rest_json = await resp.json()
            last_block_height = rest_json.get('height')
    if not maxCount:
        max_count = 10
    else:
        max_count = maxCount
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

            return resp_json

@app.get('/v2-pairs')
async def get_v2_pairs_data(
    request: Request,
    response: Response,
    contract: str
):
    all_pair_contracts = read_json_file('static/cached_pair_addresses.json')
    
    if all_pair_contracts and len(all_pair_contracts) <= 0:
        return {"error": "No data found"}

    redis_conn_raw = await request.app.redis_pool.acquire()
    redis_conn: aioredis.Redis = aioredis.Redis(redis_conn_raw)
    all_pair_contracts = [uniswap_pair_contract_V2_pair_data.format(f"{Web3.toChecksumAddress(addr)}") for addr in all_pair_contracts]
    data = await redis_conn.mget(*all_pair_contracts)
    request.app.redis_pool.release(redis_conn_raw)

    if data:
        data = [json.loads(pair_data) for pair_data in data]
    else:
        data = {"error": "No data found"}
    
    return data


@app.get('/request_status/{requestId:str}')
async def check_request(
        request: Request,
        response: Response,
        requestId: str,
):
    request_url = urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL, f'/requests/{requestId}')

    async with aiohttp.ClientSession() as session:
        async with session.get(url=request_url) as resp:
            resp_json = await resp.json()
            if 'requestStatus' in resp_json:
                if resp_json['requestStatus'] == 'Completed':
                    # Retrieve the request info data from redis
                    redis_conn_raw = await request.app.redis_pool.acquire()
                    redis_conn: aioredis.Redis = aioredis.Redis(redis_conn_raw)
                    request_info_key = f"pendingRequestInfo:{requestId}"
                    out = await redis_conn.get(request_info_key)
                    if out:
                        request_data = json.loads(out.decode('utf-8'))
                    else:
                        return {'error': 'Invalid requestId'}
                    request.app.redis_pool.release(redis_conn_raw)

                    # Make a call to payloads to retrieve the data
                    query_params = {
                        'from_height': int(request_data['fromHeight']),
                        'to_height': int(request_data['toHeight']),
                        'data': request_data['data']
                    }
                    range_fetch_url = urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL,
                                              f"/{request_data['projectId']}/payloads/")
                    async with aiohttp.ClientSession() as fetch_session:
                        async with fetch_session.get(url=range_fetch_url, params=query_params) as fetch_resp:
                            fetch_resp_json = await fetch_resp.json()

                            if isinstance(fetch_resp_json, dict):
                                if 'requestId' in fetch_resp_json:
                                    # The old request has been completed but the span data has also been destroyed
                                    # save this request data and delete the old one

                                    _ = await save_request_data(
                                        request=request,
                                        request_id=fetch_resp_json['requestId'],
                                        max_count=request_data['maxCount'],
                                        from_height=request_data['fromHeight'],
                                        to_height=request_data['toHeight'],
                                        data=request_data['data'],
                                        project_id=request_data['projectId'],
                                    )

                            _ = await delete_request_data(request=request, request_id=requestId)

                            return fetch_resp_json
            return resp_json


@app.get('/snapshot/{marketId:str}')
async def get_last_snapshot(
        request: Request,
        response: Response,
        marketId: str,
        cached: Optional[str] = Query("false"),
        diffs: Optional[str] = Query("false"),
        audit_project_id: str = Depends(project_namespace_inject)
):
    fetch_from_cache = None
    if not cached:
        fetch_from_cache = False
    elif cached.lower() == 'true':
        fetch_from_cache = True
    else:
        fetch_from_cache = False
    if not diffs:
        diffs = False
    elif diffs.lower() == 'true':
        diffs = True
    else:
        diffs = False
    redis_conn_raw = await request.app.redis_pool.acquire()
    redis_conn: aioredis.Redis = aioredis.Redis(redis_conn_raw)
    last_payload = None
    # TODO: handle when fetch from cache is set to false
    if not fetch_from_cache:
        last_snapshot_key = f'polymarket:market:{audit_project_id}:cachedSnapshot'
        r = await redis_conn.get(last_snapshot_key)
        if not r:
            return {'error': 'NoCachedSnapshot'}
        else:
            last_payload = json.loads(r)
        last_block_height_url = urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL, f'/{audit_project_id}/payloads/height')
        async with aiohttp.ClientSession() as session:
            async with session.get(url=last_block_height_url) as resp:
                rest_json = await resp.json()
                market_latest_height = rest_json.get('height')
        last_to_last_payload = await get_last_to_last_payload(market_latest_height, audit_project_id)
        diff_map = dict()
        if last_to_last_payload and diffs:
            rest_logger.debug('Comparing between last and last to last payloads')
            rest_logger.debug(last_payload)
            rest_logger.debug(last_to_last_payload)

            for k, v in last_payload.items():
                if k not in last_to_last_payload.keys():
                    rest_logger.info('Ignoring key in older payload as it is not present')
                    rest_logger.info(k)
                    continue
                if v != last_to_last_payload[k]:
                    diff_map[k] = {'old': last_to_last_payload[k], 'new': v}
        request.app.redis_pool.release(redis_conn_raw)
        return {
            'lastSnapshot': last_payload,
            'lastToLastSnapshot': last_to_last_payload,
            'diff': diff_map
        }


@app.get('/trade/{marketIdentity}')
@provide_async_redis_conn
async def get_trade_vol_value(
        request: Request,
        response: Response,
        marketIdentity: str,
        redis_conn=None
):
    if marketIdentity[:2] != "0x":
        contract_address = await get_market_address(market_id=marketIdentity, redis_conn=redis_conn)
        if contract_address == -1:
            return {'error': 'Unknown marketId'}
    else:
        contract_address = marketIdentity.lower()

    cached_trade_vol_key = f"cachedTradeVolume:{contract_address}"
    trade_vol_data = await redis_conn.get(cached_trade_vol_key)
    if trade_vol_data:
        json_trade_vol_data = json.loads(trade_vol_data.decode('utf-8'))
        rest_logger.debug("Got the trade volume for given market: ")
        rest_logger.debug({'trade_json': json_trade_vol_data, 'marketIdentity': marketIdentity})
        return json_trade_vol_data
    else:
        return {'error': "Trade volume not available for this market."
                         "Please recheck the marketId/marketMakerAddress"}


@app.get('/liquidity/{marketIdentity}')
@provide_async_redis_conn
async def get_liquidity(
        request: Request,
        response: Response,
        marketIdentity: str,
        redis_conn=None
):
    if marketIdentity[:2] != "0x":
        contract_address = await get_market_address(market_id=marketIdentity, redis_conn=redis_conn)
        if contract_address == -1:
            return {'error': 'Unknown marketId'}
    else:
        contract_address = marketIdentity.lower()

    cached_liquidity_key = f"cachedLiquidity:{contract_address}"
    liquidity = await redis_conn.get(cached_liquidity_key)
    if liquidity:
        liquidity = json.loads(liquidity.decode('utf-8'))
    else:
        return {'error': "Liquidity not available for this market."
                         "Please recheck the marketId/marketMakerAddress"}
    rest_logger.debug("Got the liquidity for given market: ")
    rest_logger.debug({'liquidity': liquidity, 'marketIdentity': marketIdentity})
    return liquidity


@app.get('/outcomePrices/{marketIdentity}')
@provide_async_redis_conn
async def get_outcome_prices(
        request: Request,
        response: Response,
        marketIdentity:  str,
        redis_conn=None
):

    if marketIdentity[:2] != "0x":
        contract_address = await get_market_address(market_id=marketIdentity, redis_conn=redis_conn)
        if contract_address == -1:
            return {'error': 'Unknown marketId'}
    else:
        contract_address = marketIdentity.lower()

    cached_outcome_prices_key = f"cachedOutcomePrices:{contract_address}"
    outcome_prices = await redis_conn.get(cached_outcome_prices_key)
    rest_logger.debug({"Outcome Prices": outcome_prices, "marketIdentity": marketIdentity})
    if outcome_prices:
        outcome_prices = outcome_prices.decode('utf-8')
        try:
            outcome_prices = json.loads(outcome_prices)
            return outcome_prices
        except json.JSONDecodeError as jerr:
            rest_logger.debug("Failed to load outcome prices")
            rest_logger.error(jerr, exc_info=True)
    return {'error': "Outcome prices unavailable"}


@app.get('/diffs/{marketId}')
async def get_state(
        request: Request,
        marketId: str,
        maxCount: int = Query(default=10),
        audit_project_id: str = Depends(project_namespace_inject)
):
    if not maxCount:
        maxCount = 1
    query_params = {'maxCount': maxCount}
    range_fetch_url = urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL, f'/{audit_project_id}/payloads/cachedDiffs')
    async with aiohttp.ClientSession() as session:
        async with session.get(url=range_fetch_url, params=query_params) as resp:
            resp_json = await resp.json()
            return resp_json
    # return {'status': 'OK'}


async def get_last_to_last_payload(market_latest_height, market_id):
    query_params = {'from_height': market_latest_height - 1, 'to_height': market_latest_height - 1, 'data': 'true'}
    async with aiohttp.ClientSession() as session:
        async with session.get(url=urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL, f'/{market_id}/payloads'),
                               params=query_params) as resp:
            resp_json = await resp.json()
            try:
                data = json.loads(resp_json[0]['Data']['payload'])
            except:
                data = None
            return data


