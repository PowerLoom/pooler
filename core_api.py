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
from math import floor

import redis_keys
from redis_conn import RedisPoolCache
from functools import reduce
from uniswap_functions import read_json_file
from redis_keys import (
    uniswap_pair_contract_V2_pair_data, uniswap_pair_cached_recent_logs, uniswap_token_info_cached_data,
    uniswap_pair_cache_daily_stats, uniswap_V2_summarized_snapshots_zset, uniswap_V2_snapshot_at_blockheight
)
from utility_functions import (
    v2_pair_data_unpack, 
    number_to_abbreviated_string
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
    app.aioredis_pool = RedisPoolCache()
    await app.aioredis_pool.populate()
    app.redis_pool = app.aioredis_pool._aioredis_pool


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
    redis_conn = await request.app.redis_pool
    c = await redis_conn.get('polymarket:markets:stats')
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


def get_tokens_liquidity_for_sort(pairData):
    return pairData["token0LiquidityUSD"] + pairData["token1LiquidityUSD"]


@app.get('/v2-pairs')
async def get_v2_pairs_data(
    request: Request,
    response: Response
):
    all_pair_contracts = read_json_file('static/cached_pair_addresses.json')
    
    if all_pair_contracts and len(all_pair_contracts) <= 0:
        return {"error": "No data found"}

    redis_conn = request.app.redis_pool
    all_pair_contracts = [uniswap_pair_contract_V2_pair_data.format(f"{Web3.toChecksumAddress(addr)}") for addr in all_pair_contracts]
    data = await redis_conn.mget(*all_pair_contracts)

    if data:
        data = [json.loads(pair_data) for pair_data in data if pair_data is not None]
        data.sort(key=get_tokens_liquidity_for_sort, reverse=True)
    else:
        data = {"error": "No data found"}
    
    return data


@app.get('/v2-pairs/snapshots')
async def get_v2_pairs_data(
    request: Request,
    response: Response
):
    redis_conn: aioredis.Redis = request.app.redis_pool
    return {
        'snapshots': list(map(
            lambda x: int(x[1]),
            await redis_conn.zrange(
                name=uniswap_V2_summarized_snapshots_zset,
                start=0,
                end=-1,
                withscores=True
            )
        ))
    }


@app.get('/v2-pairs/{block_height:int}')
async def get_v2_pairs_data(
    request: Request,
    response: Response,
    block_height: int
):
    redis_conn: aioredis.Redis = request.app.redis_pool
    _ = await redis_conn.zrangebyscore(
        name=redis_keys.uniswap_V2_summarized_snapshots_zset,
        min=block_height,
        max=block_height,
        withscores=False
    )

    if _:
        return json.loads(await redis_conn.get(
            name=redis_keys.uniswap_V2_snapshot_at_blockheight.format(block_height)
        ))['data']
    return {
        'data': None
    }


@app.get('/v2_pairs_recent_logs')
async def get_v2_pairs_recent_logs(
    request: Request,
    response: Response,
    pair_contract: str
):
    redis_conn = await request.app.redis_pool
    data = await redis_conn.get(uniswap_pair_cached_recent_logs.format(f"{Web3.toChecksumAddress(pair_contract)}"))

    if data:
        data = json.loads(data)
    else:
        data = {"error": "No data found"}
    
    return data

def get_pair_liquidity_for_sort(tokenData):
    return tokenData["liquidityUSD"]

@app.get('/v2_tokens')
async def get_v2_pairs_recent_logs(
    request: Request,
    response: Response
):
    redis_conn = await request.app.redis_pool

    # get all keys of uniswap v2 tokens
    keys = await redis_conn.keys(uniswap_token_info_cached_data.format("*"))
    if keys:
        keys = [key.decode('utf-8') for key in keys]
    else:
        keys=[]

    # get data associated to those key
    data = await redis_conn.mget(*keys)

    if data:
        data = [json.loads(obj) for obj in data]
        data.sort(key=get_pair_liquidity_for_sort, reverse=True)
        temp = []
        for i in range(len(data)):
            temp.append({
                "index": i+1,
                "name": data[i]["name"],
                "symbol": data[i]["symbol"],
                "liquidity": f"US${round(abs(data[i]['liquidityUSD'])):,}",
                "volume_24h": f"US${round(abs(data[i]['tradeVolumeUSD_24h'])):,}",
                "price": f"US${round(abs(data[i]['price']), 5):,}",
                "price_change_24h": f"{round(data[i]['priceChangePercent_24h'], 2)}%",
                "block_height": int(data[i]["block_height"])
            })
        data = temp
    else:
        data = {"error": "No data found"}
    
    return data



@app.get('/v2_daily_stats')
async def get_v2_pairs_daily_stats(
    request: Request,
    response: Response
):
    try:

        redis_conn = await request.app.redis_pool

        # get all keys of uniswap v2 tokens
        keys = await redis_conn.keys(uniswap_pair_cache_daily_stats.format("*"))
        if not keys:
            rest_logger.error(f"Error in get_v2_pairs_daily_stats: no data found in redis: {redis_conn.keys(uniswap_pair_cache_daily_stats.format('*'))}")
            return {"error": "No data found"}

        keys = [key.decode('utf-8') for key in keys]
        daily_stats = {
            "volume24": { "currentValue": 0, "previousValue": 0, "change": 0},
            "tvl": { "currentValue": 0, "previousValue": 0, "change": 0},
            "fees24": { "currentValue": 0, "previousValue": 0, "change": 0}
        }
        for key in keys:
            data = await redis_conn.zrangebyscore(
                name=key,
                min=float('-inf'),
                max=float('inf')
            )

            if data:
                # aggregate trade volume and liquidity across all pairs
                data = [json.loads(json.loads(obj)) for obj in data]
                daily_stats["volume24"]["currentValue"] += v2_pair_data_unpack(data[len(data) - 1]["volume_24h"])
                daily_stats["volume24"]["previousValue"] += v2_pair_data_unpack(data[0]["volume_24h"])
                
                daily_stats["tvl"]["currentValue"] += v2_pair_data_unpack(data[len(data) - 1]["liquidity"])
                daily_stats["tvl"]["previousValue"] += v2_pair_data_unpack(data[0]["liquidity"])
                
                daily_stats["fees24"]["currentValue"] += v2_pair_data_unpack(data[len(data) - 1]["fees_24h"])
                daily_stats["fees24"]["previousValue"] += v2_pair_data_unpack(data[0]["fees_24h"])
        
        # calculate percentage change
        if daily_stats["volume24"]["previousValue"] != 0: 
            daily_stats["volume24"]["change"] = daily_stats["volume24"]["currentValue"] - daily_stats["volume24"]["previousValue"]
            daily_stats["volume24"]["change"] = daily_stats["volume24"]["change"] / daily_stats["volume24"]["previousValue"] * 100
        
        if daily_stats["tvl"]["previousValue"] != 0:
            daily_stats["tvl"]["change"] = daily_stats["tvl"]["currentValue"] - daily_stats["tvl"]["previousValue"]
            daily_stats["tvl"]["change"] = daily_stats["tvl"]["change"] / daily_stats["tvl"]["previousValue"] * 100

        if daily_stats["fees24"]["previousValue"] != 0:
            daily_stats["fees24"]["change"] = daily_stats["fees24"]["currentValue"] - daily_stats["fees24"]["previousValue"]
            daily_stats["fees24"]["change"] = daily_stats["fees24"]["change"] / daily_stats["fees24"]["previousValue"] * 100


        # format output
        daily_stats["volume24"]["currentValue"] = f"US${number_to_abbreviated_string(round(daily_stats['volume24']['currentValue'], 2))}"
        daily_stats["volume24"]["previousValue"] = f"US${number_to_abbreviated_string(round(daily_stats['volume24']['previousValue'], 2))}"
        daily_stats["volume24"]["change"] = f"{round(daily_stats['volume24']['change'], 2)}%"

        daily_stats["tvl"]["currentValue"] = f"US${number_to_abbreviated_string(round(daily_stats['tvl']['currentValue'], 2))}"
        daily_stats["tvl"]["previousValue"] = f"US${number_to_abbreviated_string(round(daily_stats['tvl']['previousValue'], 2))}"
        daily_stats["tvl"]["change"] = f"{round(daily_stats['tvl']['change'], 2)}%"

        daily_stats["fees24"]["currentValue"] = f"US${number_to_abbreviated_string(round(daily_stats['fees24']['currentValue'], 2))}"
        daily_stats["fees24"]["previousValue"] = f"US${number_to_abbreviated_string(round(daily_stats['fees24']['previousValue'], 2))}"
        daily_stats["fees24"]["change"] = f"{round(daily_stats['fees24']['change'], 2)}%"

        return daily_stats
    except Exception as e:
        rest_logger.error(f"Error in get_v2_pairs_daily_stats: {str(e)}", exc_info=True)
        return {"error": "No data found"}

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
                    redis_conn = await request.app.redis_pool
                    request_info_key = f"pendingRequestInfo:{requestId}"
                    out = await redis_conn.get(request_info_key)
                    if out:
                        request_data = json.loads(out.decode('utf-8'))
                    else:
                        return {'error': 'Invalid requestId'}

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
    redis_conn = await request.app.redis_pool
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
        return {
            'lastSnapshot': last_payload,
            'lastToLastSnapshot': last_to_last_payload,
            'diff': diff_map
        }


@app.get('/trade/{marketIdentity}')
async def get_trade_vol_value(
        request: Request,
        response: Response,
        marketIdentity: str
):
    redis_conn: aioredis.Redis = request.app.redis_pool
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
async def get_liquidity(
        request: Request,
        response: Response,
        marketIdentity: str
):
    redis_conn: aioredis.Redis = request.app.redis_pool
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
async def get_outcome_prices(
        request: Request,
        response: Response,
        marketIdentity:  str
):
    redis_conn: aioredis.Redis = request.app.redis_pool
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


