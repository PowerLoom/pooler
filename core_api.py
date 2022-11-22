from typing import Optional
from urllib.parse import urljoin
import logging
import sys
import json
import os

from fastapi import Depends, FastAPI, Request, Response, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dynaconf import settings
import coloredlogs
from redis import asyncio as aioredis
import aiohttp
from web3 import Web3

import redis_keys
from redis_conn import RedisPoolCache
from uniswap_functions import read_json_file
from redis_keys import (
    uniswap_pair_cached_recent_logs,uniswap_pair_contract_tokens_addresses,
    uniswap_V2_summarized_snapshots_zset, uniswap_V2_snapshot_at_blockheight,
    uniswap_v2_daily_stats_snapshot_zset, uniswap_V2_daily_stats_at_blockheight,
    uniswap_v2_tokens_snapshot_zset,uniswap_V2_tokens_at_blockheight

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
            f_ = open("static/cached_markets.json", 'r')
        except Exception as exc:
            rest_logger.warning("Unable to open the cached_markets.json file")
            rest_logger.error(exc, exc_info=True)
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


@app.get('/v1/api/v2-pairs')
@app.get('/v2-pairs')
async def get_v2_pairs_data(
    request: Request,
    response: Response
):
    redis_conn = request.app.redis_pool
    latest_v2_summary_snapshot = await redis_conn.zrevrange(
        name=uniswap_V2_summarized_snapshots_zset,
        start=0,
        end=0,
        withscores=True
    )

    if len(latest_v2_summary_snapshot) < 1:
        return {'data': None}

    latest_payload, latest_block_height = latest_v2_summary_snapshot[0]
    latest_payload = json.loads(latest_payload.decode('utf-8'))
    latest_payload_cid = latest_payload.get("cid")
    tx_hash = latest_payload.get("txHash")
    tx_status = latest_payload.get("txStatus")
    prev_tx_hash = latest_payload.get("prevTxHash")
    begin_block_height_24h = latest_payload.get("begin_block_height_24h")
    begin_block_timestamp_24h = latest_payload.get("begin_block_timestamp_24h")
    begin_block_height_7d = latest_payload.get("begin_block_height_7d")
    begin_block_timestamp_7d = latest_payload.get("begin_block_timestamp_7d")


    snapshot_data = await redis_conn.get(
        name=uniswap_V2_snapshot_at_blockheight.format(int(latest_block_height))
    )
    if not snapshot_data:
        # fetch from ipfs
        snapshot_data = await retrieve_payload_data(latest_payload_cid, redis_conn)

    #even ipfs doesn't have the data, return empty
    if not snapshot_data:
        return {'data': None}

    data = json.loads(snapshot_data)["data"]
    data.sort(key=get_tokens_liquidity_for_sort, reverse=True)

    if "/v1/api" in request.url._url:
        return {
            "data": data, "txHash": tx_hash, "cid": latest_payload_cid,
            "txStatus": SNAPSHOT_STATUS_MAP[tx_status], "prevTxHash": prev_tx_hash,
            "block_height": data[0].get("block_height", None), "block_timestamp": data[0].get("block_timestamp", None),
            "begin_block_height_24h": begin_block_height_24h, "begin_block_timestamp_24h": begin_block_timestamp_24h,
            "begin_block_height_7d": begin_block_height_7d, "begin_block_timestamp_7d": begin_block_timestamp_7d
        }
    else:
        return data

@app.get('/v1/api/v2-pairs/snapshots')
@app.get('/v2-pairs/snapshots')
async def get_v2_pairs_snapshots(
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


@app.get('/v1/api/v2-pairs/{block_height:int}')
@app.get('/v2-pairs/{block_height:int}')
async def get_v2_pairs_at_block_height(
    request: Request,
    response: Response,
    block_height: int
):
    redis_conn: aioredis.Redis = request.app.redis_pool

    snapshot_data = await redis_conn.get(
        name=redis_keys.uniswap_V2_snapshot_at_blockheight.format(block_height)
    )

    latest_payload = await redis_conn.zrangebyscore(
        name=redis_keys.uniswap_V2_summarized_snapshots_zset,
        min=block_height,
        max=block_height,
        withscores=False
    )

    if len(latest_payload) < 1:
        return {'data': None}

    latest_payload = json.loads(latest_payload[0].decode('utf-8'))
    payload_cid = latest_payload.get("cid")
    tx_hash = latest_payload.get("txHash")
    tx_status = latest_payload.get("txStatus")
    prev_tx_hash = latest_payload.get("prevTxHash")
    begin_block_height_24h = latest_payload.get("begin_block_height_24h")
    begin_block_timestamp_24h = latest_payload.get("begin_block_timestamp_24h")
    begin_block_height_7d = latest_payload.get("begin_block_height_7d")
    begin_block_timestamp_7d = latest_payload.get("begin_block_timestamp_7d")

    # serve redis cache
    if snapshot_data:
        data = json.loads(snapshot_data)['data']
        data.sort(key=get_tokens_liquidity_for_sort, reverse=True)
        if "/v1/api" in request.url._url:
            return {
                "data": data, "txHash": tx_hash, "cid": payload_cid,
                "txStatus": SNAPSHOT_STATUS_MAP[tx_status], "prevTxHash": prev_tx_hash,
                "block_height": block_height, "block_timestamp": data[0].get("block_timestamp", None),
                "begin_block_height_24h": begin_block_height_24h, "begin_block_timestamp_24h": begin_block_timestamp_24h,
                "begin_block_height_7d": begin_block_height_7d, "begin_block_timestamp_7d": begin_block_timestamp_7d
            }
        else:
            return data

    # fetch from ipfs
    payload_data = await retrieve_payload_data(payload_cid, redis_conn)

    if not payload_data:
        payload_data = {"data": None}

    payload_data = json.loads(payload_data)['data']
    payload_data.sort(key=get_tokens_liquidity_for_sort, reverse=True)

    if "/v1/api" in request.url._url:
        return {
            "data": payload_data, "txHash": tx_hash, "cid": payload_cid,
            "block_height": block_height, "block_timestamp": payload_data[0].get("block_timestamp", None),
            "begin_block_height_24h": begin_block_height_24h, "begin_block_timestamp_24h": begin_block_timestamp_24h,
            "begin_block_height_7d": begin_block_height_7d, "begin_block_timestamp_7d": begin_block_timestamp_7d
        }
    else:
        return payload_data


@app.get('/v1/api/v2-daily-stats/snapshots')
@app.get('/v2-daily-stats/snapshots')
async def get_v2_daily_stats_snapshot(
    request: Request,
    response: Response
):
    redis_conn: aioredis.Redis = request.app.redis_pool
    return {
        'snapshots': list(map(
            lambda x: int(x[1]),
            await redis_conn.zrange(
                name=uniswap_v2_daily_stats_snapshot_zset,
                start=0,
                end=-1,
                withscores=True
            )
        ))
    }

@app.get('/v1/api/v2-daily-stats/{block_height:int}')
@app.get('/v2-daily-stats/{block_height:int}')
async def get_v2_daily_stats_by_block(
    request: Request,
    response: Response,
    block_height: int
):
    redis_conn: aioredis.Redis = request.app.redis_pool
    latest_payload = await redis_conn.zrangebyscore(
        name=uniswap_v2_daily_stats_snapshot_zset,
        min=block_height,
        max=block_height,
        withscores=False
    )

    if len(latest_payload) < 1:
        return {'data': None}

    latest_payload = json.loads(latest_payload[0].decode('utf-8'))
    payload_cid = latest_payload.get("cid")
    tx_hash = latest_payload.get("txHash")
    tx_status = latest_payload.get("txStatus")
    prev_tx_hash = latest_payload.get("prevTxHash")


    try:
        snapshot_data = await redis_conn.get(
            name=uniswap_V2_daily_stats_at_blockheight.format(block_height)
        )
        if not snapshot_data:
            # fetch from ipfs
            payload_cid = payload_cid.decode('utf-8') if type(payload_cid) == bytes else payload_cid
            snapshot_data = await retrieve_payload_data(payload_cid, redis_conn)

        # even ipfs doesn't have payload then exit
        if not snapshot_data:
            return {'data': None}

        snapshot_data = json.loads(snapshot_data)['data']

        daily_stats = {
            "volume24": { "currentValue": 0, "previousValue": 0, "change": 0},
            "tvl": { "currentValue": 0, "previousValue": 0, "change": 0},
            "fees24": { "currentValue": 0, "previousValue": 0, "change": 0}
        }
        for contract_obj in snapshot_data:
            if contract_obj:
                # aggregate trade volume and liquidity across all pairs
                daily_stats["volume24"]["currentValue"] += contract_obj["volume24"]["currentValue"]
                daily_stats["volume24"]["previousValue"] += contract_obj["volume24"]["previousValue"]

                daily_stats["tvl"]["currentValue"] += contract_obj["tvl"]["currentValue"]
                daily_stats["tvl"]["previousValue"] += contract_obj["tvl"]["previousValue"]

                daily_stats["fees24"]["currentValue"] += contract_obj["fees24"]["currentValue"]
                daily_stats["fees24"]["previousValue"] += contract_obj["fees24"]["previousValue"]

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

        if "/v1/api" in request.url._url:
            return {
                "data": daily_stats, "txHash": tx_hash, "cid": payload_cid,
                "txStatus": SNAPSHOT_STATUS_MAP[tx_status], "prevTxHash": prev_tx_hash,
                "block_height": snapshot_data[0].get("block_height", None), "block_timestamp": snapshot_data[0].get("block_timestamp", None)
            }
        else:
            return daily_stats

    except Exception as err:
        print(f"Error in daily stats by block height err: {str(err)} ")
        return {
            'data': None
        }


@app.get('/v2-pairs-recent-logs')
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

@app.get('/v2-tokens-recent-logs')
async def get_v2_tokens_recent_logs(
    request: Request,
    response: Response,
    token_contract: str
):
    pair_tokens_addresses = {}
    all_pair_contracts = read_json_file('static/cached_pair_addresses.json',rest_logger)
    redis_conn = await request.app.redis_pool

    # get pair's token addresses ( pair -> token0, token1)
    redis_pipe = redis_conn.pipeline()
    pair_logs_keys = []
    for pair in all_pair_contracts:
        redis_pipe.hgetall(uniswap_pair_contract_tokens_addresses.format(Web3.toChecksumAddress(pair)))
        pair_logs_keys.append(uniswap_pair_cached_recent_logs.format(Web3.toChecksumAddress(pair)))
    tokens_address = await redis_pipe.execute()

    # map pair to token adresses
    for i in range(len(tokens_address)):
        pair_tokens_addresses[pair_logs_keys[i]] = tokens_address[i]

    # filter pairs whos have given token contract
    def filter_token(map):
        nonlocal token_contract
        token0 = map[b'token0Addr'].decode('utf-8')
        token1 = map[b'token1Addr'].decode('utf-8')
        token_contract = Web3.toChecksumAddress(token_contract)
        return token0 == token_contract or token1 == token_contract

    # filter by token address
    pair_tokens_addresses = {k:v for (k,v) in pair_tokens_addresses.items() if filter_token(v)}

    # get recent logs of filtered pairs
    pairs_log = await redis_conn.mget(*pair_tokens_addresses.keys())

    temp = []
    for pair_log in pairs_log:
        pairs_log = json.loads(pair_log)
        temp += pairs_log
    pairs_log = sorted(temp, key=lambda d: d['timestamp'], reverse=True)
    if len(pairs_log) > 75:
        pairs_log = pairs_log[:75]

    return pairs_log

def sort_on_liquidity(tokenData):
    return tokenData["liquidityUSD"]

@app.get('/v1/api/v2-tokens')
@app.get('/v2-tokens')
async def get_v2_tokens(
    request: Request,
    response: Response
):
    redis_conn = await request.app.redis_pool

    latest_daily_stats_snapshot = await redis_conn.zrevrange(
        name=uniswap_v2_tokens_snapshot_zset,
        start=0,
        end=0,
        withscores=True
    )

    if len(latest_daily_stats_snapshot) < 1:
        return {'data': None}

    latest_payload, latest_block_height = latest_daily_stats_snapshot[0]
    latest_payload = json.loads(latest_payload.decode('utf-8'))
    latest_payload_cid = latest_payload.get("cid")
    tx_hash = latest_payload.get("txHash")
    tx_status = latest_payload.get("txStatus")
    prev_tx_hash = latest_payload.get("prevTxHash")

    snapshot_data = await redis_conn.get(
        name=uniswap_V2_tokens_at_blockheight.format(int(latest_block_height))
    )
    if not snapshot_data:
        # fetch from ipfs
        latest_payload_cid = latest_payload_cid.decode('utf-8') if type(latest_payload_cid) == bytes else latest_payload_cid
        snapshot_data = await retrieve_payload_data(latest_payload_cid, redis_conn)

        # even ipfs doesn't have data, return empty
        if not snapshot_data:
            return {'data': None}

        data = json.loads(snapshot_data)['data']
    else:
        data = json.loads(snapshot_data)

    data = create_v2_token_snapshot(data)

    if "/v1/api" in request.url._url:
        return {
            "data": data, "txHash": tx_hash, "cid": latest_payload_cid,
            "txStatus": SNAPSHOT_STATUS_MAP[tx_status], "prevTxHash": prev_tx_hash,
            "block_height": data[0].get("block_height", None), "block_timestamp": data[0].get("block_timestamp", None)
        }
    else:
        return data


def create_v2_token_snapshot(data):
    data.sort(key=sort_on_liquidity, reverse=True)
    temp = []
    for i in range(len(data)):
        temp.append({
            "index": i+1,
            "contract_address":data[i]["contractAddress"],
            "name": data[i]["name"],
            "symbol": data[i]["symbol"],
            "liquidity": f"US${round(abs(data[i]['liquidityUSD'])):,}",
            "volume_24h": f"US${round(abs(data[i]['tradeVolumeUSD_24h'])):,}",
            "volume_7d":f"US${round(abs(data[i]['tradeVolumeUSD_7d']))}",
            "price": f"US${round(abs(data[i]['price']), 5):,}",
            "price_change_24h": f"{round(data[i]['priceChangePercent_24h'], 2)}%",
            "block_height": int(data[i]["block_height"]),
            "block_timestamp": int(data[i]["block_timestamp"])
        })
    return temp

@app.get('/v1/api/v2-tokens/snapshots')
@app.get('/v2-tokens/snapshots')
async def get_v2_tokens_snapshots(
    request: Request,
    response: Response
):
    redis_conn: aioredis.Redis = request.app.redis_pool
    return {
        'snapshots': list(map(
            lambda x: int(x[1]),
            await redis_conn.zrange(
                name=uniswap_v2_tokens_snapshot_zset,
                start=0,
                end=-1,
                withscores=True
            )
        ))
    }

@app.get('/v1/api/v2-tokens/{block_height:int}')
@app.get('/v2-tokens/{block_height:int}')
async def get_v2_tokens_data_by_block(
    request: Request,
    response: Response,
    block_height: int
):
    redis_conn: aioredis.Redis = request.app.redis_pool
    latest_payload = await redis_conn.zrangebyscore(
        name=uniswap_v2_tokens_snapshot_zset,
        min=block_height,
        max=block_height,
        withscores=False
    )

    if len(latest_payload) < 1:
        return {'data': None}

    latest_payload = json.loads(latest_payload[0].decode('utf-8'))
    payload_cid = latest_payload.get("cid")
    txHash = latest_payload.get("txHash")
    txStatus = latest_payload.get("txStatus")
    prevTxHash = latest_payload.get("prevTxHash")

    snapshot_data = await redis_conn.get(
        name=uniswap_V2_tokens_at_blockheight.format(block_height)
    )
    if not snapshot_data:
        # fetch from ipfs
        snapshot_data = await retrieve_payload_data(payload_cid, redis_conn)

        # even ipfs doesn't have data, return empty
        if not snapshot_data:
            return {'data': None}

        snapshot_data = json.loads(snapshot_data)['data']
    else:
        snapshot_data = snapshot_data.decode('utf-8')
        snapshot_data = json.loads(snapshot_data)

    snapshot_data = create_v2_token_snapshot(snapshot_data)

    if "/v1/api" in request.url._url:
        return {
            "data": snapshot_data, "txHash": txHash, "cid": payload_cid,
            "txStatus": SNAPSHOT_STATUS_MAP[txStatus], "prevTxHash": prevTxHash,
            "block_height": snapshot_data[0].get("block_height", None), "block_timestamp": snapshot_data[0].get("block_timestamp", None)
        }
    else:
        return snapshot_data


@app.get('/v1/api/v2-daily-stats')
@app.get('/v2-daily-stats')
async def get_v2_pairs_daily_stats(
    request: Request,
    response: Response
):
    try:

        redis_conn = await request.app.redis_pool
        latest_daily_stats_snapshot = await redis_conn.zrevrange(
            name=uniswap_v2_daily_stats_snapshot_zset,
            start=0,
            end=0,
            withscores=True
        )

        if len(latest_daily_stats_snapshot) < 1:
            return {'data': None}

        latest_payload, latest_block_height = latest_daily_stats_snapshot[0]
        latest_payload = json.loads(latest_payload.decode('utf-8'))
        payload_cid = latest_payload.get("cid")
        txHash = latest_payload.get("txHash")
        txStatus = latest_payload.get("txStatus")
        prevTxHash = latest_payload.get("prevTxHash")


        snapshot_data = await redis_conn.get(
            name=uniswap_V2_daily_stats_at_blockheight.format(int(latest_block_height))
        )
        if not snapshot_data:
            # fetch from ipfs
            payload_cid = payload_cid.decode('utf-8') if type(payload_cid) == bytes else payload_cid
            snapshot_data = await retrieve_payload_data(payload_cid, redis_conn)

        # even ipfs doesn't have payload then exit
        if not snapshot_data:
            return {'data': None}

        snapshot_data = json.loads(snapshot_data)["data"]

        daily_stats = {
            "volume24": { "currentValue": 0, "previousValue": 0, "change": 0},
            "tvl": { "currentValue": 0, "previousValue": 0, "change": 0},
            "fees24": { "currentValue": 0, "previousValue": 0, "change": 0}
        }
        for contract_obj in snapshot_data:
            if contract_obj:
                # aggregate trade volume and liquidity across all pairs
                daily_stats["volume24"]["currentValue"] += contract_obj["volume24"]["currentValue"]
                daily_stats["volume24"]["previousValue"] += contract_obj["volume24"]["previousValue"]

                daily_stats["tvl"]["currentValue"] += contract_obj["tvl"]["currentValue"]
                daily_stats["tvl"]["previousValue"] += contract_obj["tvl"]["previousValue"]

                daily_stats["fees24"]["currentValue"] += contract_obj["fees24"]["currentValue"]
                daily_stats["fees24"]["previousValue"] += contract_obj["fees24"]["previousValue"]

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

        if "/v1/api" in request.url._url:
            return {
                "data": daily_stats, "txHash": txHash, "cid": payload_cid,
                "txStatus": SNAPSHOT_STATUS_MAP[txStatus], "prevTxHash": prevTxHash,
                "block_height": snapshot_data[0].get("block_height", None), "block_timestamp": snapshot_data[0].get("block_timestamp", None)
            }
        else:
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


