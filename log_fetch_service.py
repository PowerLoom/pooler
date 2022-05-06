import os
import sys
from fastapi import Depends, FastAPI, WebSocket, status, Request, Response
from starlette.status import HTTP_403_FORBIDDEN, HTTP_200_OK
from redis_conn import REDIS_CONN_CONF, RedisPoolCache
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from uuid import uuid4
from init_rabbitmq import get_rabbitmq_channel_async, get_rabbitmq_connection_async
from functools import partial
from dynaconf import settings
import aioredis
import asyncio
from aio_pika import connect, Channel, Message, DeliveryMode, ExchangeType
from aio_pika.pool import Pool
import json
import logging
from eth_log_dist_worker import get_event_sig, get_aiohttp_cache, RPCException, make_post_call_async
from message_models import ethLogRequestModel
import time


log_entry_logger = logging.getLogger('PowerLoom|EthLogs|RequestAPI')
log_entry_logger.setLevel(logging.DEBUG)
# RabbitMQ Exchange name
LOG_REQ_EXCHANGE_NAME = f'{settings.RABBITMQ.SETUP.CALLBACKS.EXCHANGE}.subtopics.{settings.ETH_LOG_WORKER.SUBTOPIC}:{settings.NAMESPACE}'

# Init App
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


@app.on_event('startup')
async def startup_boilerplate():
    app.aiohttp_session = await get_aiohttp_cache()
    app.aioredis_pool = RedisPoolCache()
    await app.aioredis_pool.populate()
    app.redis: aioredis.Redis = app.aioredis_pool._aioredis_pool
    app._rmq_connection_pool = Pool(get_rabbitmq_connection_async, max_size=5)
    app._rmq_channel_pool = Pool(partial(get_rabbitmq_channel_async, app._rmq_connection_pool), max_size=20)
    
    log_entry_logger.debug("Configured rabbitmq, redis and logger!")


@app.post("/requestEthLog")
async def request_eth_log(
        request: Request,
        response: Response,
        requestBody: ethLogRequestModel
):
    async with request.app._rmq_channel_pool.acquire() as channel:
        # parse request body
        fromBlock = requestBody.fromBlock
        toBlock = requestBody.toBlock
        contract = requestBody.contract
        topics = requestBody.topics

        # generate requestId
        requestId = str(uuid4())

        try:    
            # Declare rmq exchange
            logs_exchange = await channel.declare_exchange(
                LOG_REQ_EXCHANGE_NAME, ExchangeType.DIRECT
            )

            # Sending the message with routing_key
            routing_key = settings.ETH_LOG_WORKER.RECEIVER_QUEUE_NAME
            await logs_exchange.publish(
                Message(
                    bytes(
                        ethLogRequestModel(
                            fromBlock=fromBlock,
                            toBlock=toBlock,
                            contract=contract,
                            topics=topics,
                            requestId=requestId
                        ).json(),
                        'utf-8'
                    )
                ),
                routing_key=routing_key)
            log_entry_logger.debug(
                "Published logs request on receiver queue | contract: %s | to Block: %s | request ID: %s",
                contract, toBlock, requestId
            )
            return {"requestId": requestId, "message": "Successfully raised eth log request"}

        except Exception as e:
            log_entry_logger.error("Caught runtime exception(eth log entry service): %s" % str(e),exc_info=True)
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return {'message': 'failed eth log request', "error": str(e)}


@app.post("/requestEthLogSync")
async def request_eth_log_sync(
    request: Request,
    response: Response,
    requestBody: ethLogRequestModel
):
    # parse request body
    fromBlock = requestBody.fromBlock
    toBlock = requestBody.toBlock
    contract = requestBody.contract
    topics = requestBody.topics
    retrialCount = requestBody.retrialCount

    # validate retrial count
    retrialCount = retrialCount if int(retrialCount) > 0 and int(retrialCount) < 4 else 1

    try:    
        # generate event signatures
        event_sigs = list(map(get_event_sig, topics))
        log_entry_logger.debug('Fetching logs for event topic: %s' % event_sigs)
        if -1 in event_sigs:
            _bad_event_name = event_sigs[event_sigs.index(-1)]
            raise AssertionError(f"Unknown event_name passed: {_bad_event_name}")

        assert fromBlock < toBlock, f"from_block:{fromBlock} should be less than to_block:{toBlock}"


        # prepare request and response body structures
        requestParams = {
            "fromBlock": hex(fromBlock),
            "toBlock": hex(toBlock),
        }
        if(event_sigs != None):
            requestParams["topics"] = event_sigs
        if(contract != None):
            requestParams["address"] = contract

        rpc_json = {
            "jsonrpc": "2.0",
            "method": "eth_getLogs",
            "params": [
                requestParams
            ],
            "id": 74
        }

        response_body = {
            'contract': contract,
            'topics': topics,
            'toBlock': toBlock,
            'fromBlock': fromBlock
        }

        #log results
        result = None

        # if retrialCount is given in request params then retry util retrialCount is reached
        while(retrialCount > 0):
            
            # make post call by default has a retry(settings.RPC.LOGS_QUERY.RETRY) and timeout(settings.RPC.LOGS_QUERY.TIMEOUT) logic
            result = await asyncio.gather(make_post_call_async(
                url=settings.RPC.MATIC[0],
                params=rpc_json,
                session=request.app.aiohttp_session,
                tag=0,
                redis_conn=request.app.redis
            ), return_exceptions=True)

            #decrease retrial count
            retrialCount -= 1

            #if rate limit exceeded and retrialCount is not 0 then retry
            if isinstance(result[0], RPCException) and retrialCount > 0:
                continue
            else: 
                break
        

        #result is not None then it is a expception or list of logs
        if isinstance(result[0], RPCException):
            response_body["logs"] = None
            response_body["error"] = str(result)
            log_entry_logger.error("Caught RPCException(eth log sync service): %s" % str(result),exc_info=True)
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return { 'status': 'error', 'data': response_body}
        else:
            response_body["logs"] = result
            response_body["error"] = None

            return { 'status': 'logFetched', 'data': response_body}

    except Exception as e:
        log_entry_logger.error("Caught runtime exception(eth log sync service): %s" % str(e),exc_info=True)
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {'status': 'error', "error": str(e)}


@app.on_event("shutdown")
async def shutdown_event():
    await app._rmq_channel_pool.close()
    await app._rmq_connection_pool.close()
    app.redis.close()
    await app.redis.wait_closed()
