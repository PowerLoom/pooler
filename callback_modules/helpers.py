from redis_conn import provide_redis_conn_insta
from proto_system_logging import setup_loguru_intercept, config_logger_with_namespace
from urllib.parse import urljoin
from dynaconf import settings
from eth_utils import keccak
from setproctitle import setproctitle
from functools import partial
from loguru import logger
from uuid import uuid4
from redis_conn import RedisPoolCache, REDIS_CONN_CONF
from aio_pika import ExchangeType, IncomingMessage
from aio_pika.pool import Pool
from helper_functions import get_event_sig, parse_logs
from functools import reduce
from typing import Union
import aioredis
import aioredis_cluster
import requests
import logging
import logging.handlers
import redis
import multiprocessing
import asyncio
import signal
import aio_pika
import aiohttp
from tenacity import Retrying, stop_after_attempt

# TODO: remove polymarket specific helpers


async def get_rabbitmq_connection():
    return await aio_pika.connect_robust(
        host=settings.RABBITMQ.HOST,
        port=settings.RABBITMQ.PORT,
        virtual_host='/',
        login=settings.RABBITMQ.USER,
        password=settings.RABBITMQ.PASSWORD
    )


async def get_rabbitmq_channel(connection_pool) -> aio_pika.Channel:
    async with connection_pool.acquire() as connection:
        return await connection.channel()

class AuditProtocolCommandsHelper:
    
    @classmethod
    @provide_redis_conn_insta
    async def set_diff_rule_for_pair_reserves(cls, pair_contract_address, stream, session: aiohttp.ClientSession, redis_conn: redis.Redis = None):
        project_id = f'uniswap_pairContract_{stream}_{pair_contract_address}'
        if not redis_conn.sismember('uniswap:diffRuleSetFor', project_id):
            """ Setup diffRules for this market"""
            # retry below call given at settings.AUDIT_PROTOCOL_ENGINE.RETRY
            for attempt in Retrying(reraise=True, stop=stop_after_attempt(settings.AUDIT_PROTOCOL_ENGINE.RETRY)):
                with attempt:
                    async with session.post(
                        url=urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL, f'/{project_id}/diffRules'), 
                        json={
                            'rules': [
                                {
                                    "ruleType": "ignore",
                                    "field": "chainHeightRange",
                                    "fieldType": "map",
                                    "ignoreMemberFields": ["begin", "end"],
                                },
                                {
                                    "ruleType": "compare",
                                    "field": "totalReserves",
                                    "fieldType": "map",
                                    "operation": "listSlice",
                                    "memberFields": -1
                                },

                                {
                                    "ruleType": "ignore",
                                    "field": "broadcast_id",
                                    "fieldType": "str"
                                },

                                {
                                    "ruleType": "ignore",
                                    "field": "timestamp",
                                    "fieldType": "float"
                                }
                            ]
                        }, 
                        timeout=aiohttp.ClientTimeout(total=None, sock_read=settings.TIMEOUTS.ARCHIVAL, sock_connect=settings.TIMEOUTS.CONNECTION_INIT )
                    ) as response_obj:
                        response_status_code = response_obj.status
                    
                    response = (await response_obj.json()) or {}

                    if response_status_code in range(200, 300):
                        redis_conn.sadd('uniswap:diffRuleSetFor', project_id)
                    elif response_status_code == 500 or response_status_code == 502:
                        return {"message": f"failed with status code: {response_status_code}", "response": response} #ignore 500 and 502 errors
                    else:
                        raise Exception('Failed audit protocol engine call with status code: {} and response: {}'.format(response_status_code, response))

    @classmethod
    @provide_redis_conn_insta
    def set_commit_callback_url(cls, pair_contract_address, stream, redis_conn: redis.Redis = None):
        project_id = f'uniswap_pairContract_{stream}_{pair_contract_address}'
        if not redis_conn.sismember('uniswap:callbackURLSetFor', project_id):
            r = requests.post(
                url=urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL, f'/{project_id}/confirmations/callback'),
                json={'callbackURL': urljoin(settings.WEBHOOK_LISTENER.ROOT, settings.WEBHOOK_LISTENER.COMMIT_CONFIRMATION_CALLBACK_PATH)}
            )
            if r.status_code in range(200, 300):
                redis_conn.sadd('uniswap:callbackURLSetFor', project_id)

    @classmethod
    async def commit_payload(cls, pair_contract_address, stream, report_payload, session: aiohttp.ClientSession):
        # retry below call given at settings.AUDIT_PROTOCOL_ENGINE.RETRY
        for attempt in Retrying(reraise=True, stop=stop_after_attempt(settings.AUDIT_PROTOCOL_ENGINE.RETRY)):
            with attempt:
                project_id = f'uniswap_pairContract_{stream}_{pair_contract_address}'
                async with session.post(
                    url=urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL, 'commit_payload'), 
                    json={'payload': report_payload, 'projectId': project_id}, 
                    timeout=aiohttp.ClientTimeout(total=None, sock_read=settings.TIMEOUTS.ARCHIVAL, sock_connect=settings.TIMEOUTS.CONNECTION_INIT )
                ) as response_obj:
                    response_status_code = response_obj.status
                
                response = (await response_obj.json()) or {}

                if response_status_code in range(200, 300):
                    return response_obj
                elif response_status_code == 500 or response_status_code == 502:
                    return {"message": f"failed with status code: {response_status_code}", "response": response}#ignore 500 and 502 errors
                else:
                    raise Exception('Failed audit protocol engine call with status code: {} and response: {}'.format(response_status_code, response))


class CallbackAsyncWorker(multiprocessing.Process):
    def __init__(self, name, rmq_q, rmq_routing, **kwargs):
        self._q = rmq_q
        self._rmq_routing = rmq_routing
        self._unique_id = f'{name}-' + keccak(text=str(uuid4())).hex()[:8]
        self._redis_conn: Union[None, aioredis.Redis] = None
        super(CallbackAsyncWorker, self).__init__(name=name, **kwargs)
        setproctitle(self._unique_id)
        # logger.add(
        #     sink='logs/' + self._unique_id + '_{time}.log', rotation='20MB', retention=20, compression='gz'
        # )
        # setup_loguru_intercept()

        self._shutdown_signal_received_count = 0

    async def _shutdown_handler(self, sig, loop: asyncio.AbstractEventLoop):
        self._shutdown_signal_received_count += 1
        if self._shutdown_signal_received_count > 1:
            logging.info(f'Received exit signal {sig.name}. Not processing as shutdown sequence was already initiated...')
        else:
            logging.info(
                f'Received exit signal {sig.name}. Processing shutdown sequence...')
            tasks = [t for t in asyncio.all_tasks() if t is not
                     asyncio.current_task()]

            [task.cancel() for task in tasks]

            logging.info(f'Cancelling {len(tasks)} outstanding tasks')
            await asyncio.gather(*tasks)
            loop.stop()
            logging.info('Shutdown complete.')

    async def _rabbitmq_consumer(self, loop):
        self._rmq_connection_pool = Pool(get_rabbitmq_connection, max_size=5, loop=loop)
        self._rmq_channel_pool = Pool(partial(get_rabbitmq_channel, self._rmq_connection_pool), max_size=20,
                                      loop=loop)
        async with self._rmq_channel_pool.acquire() as channel:
            await channel.set_qos(10)
            q_obj = await channel.get_queue(
                name=self._q,
                ensure=False
            )
            self._logger.debug(f'Consuming queue {self._q} with routing key {self._rmq_routing}...')
            await q_obj.consume(self._on_rabbitmq_message)

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        await message.ack()

    async def init_redis_pool(self):
        if not self._redis_conn:
            RedisPoolCache.append_ssl_connection_params(REDIS_CONN_CONF, settings['redis'])
            redis_cluster_mode_conn = False
            try:
                if settings.REDIS.CLUSTER_MODE:
                    redis_cluster_mode_conn = True
            except:
                pass
            if redis_cluster_mode_conn:
                self._redis_conn = await aioredis_cluster.create_redis_cluster(
                    startup_nodes=[(REDIS_CONN_CONF['host'], REDIS_CONN_CONF['port'])],
                    password=REDIS_CONN_CONF['password'],
                    pool_maxsize=10,
                    ssl=REDIS_CONN_CONF['ssl']
                )
            else:
                self._redis_conn = await aioredis.create_redis_pool(
                    address=(REDIS_CONN_CONF['host'], REDIS_CONN_CONF['port']),
                    db=REDIS_CONN_CONF['db'],
                    password=REDIS_CONN_CONF['password'],
                    maxsize=10,
                    ssl=REDIS_CONN_CONF['ssl']
                )

    def run(self) -> None:
        # logging.config.dictConfig(config_logger_with_namespace(self.name))
        self._logger = logging.getLogger(self.name)
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers = [logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]
        self._redis_pool_interface = RedisPoolCache()
        ev_loop = asyncio.get_event_loop()
        signals = (signal.SIGTERM, signal.SIGINT)
        for s in signals:
            ev_loop.add_signal_handler(
                s, lambda x=s: ev_loop.create_task(self._shutdown_handler(x, ev_loop)))
        self._logger.debug(f'Starting asynchronous epoch callback worker {self._unique_id}...')
        asyncio.ensure_future(self._rabbitmq_consumer(ev_loop))
        try:
            ev_loop.run_forever()
        finally:
            ev_loop.close()


def get_event_name_from_sig(event_sig: str):
    if event_sig == get_event_sig("FPMMBuy"):
        return "FPMMBuy"
    elif event_sig == get_event_sig("FPMMSell"):
        return "FPMMSell"
    return -1


def get_trade_vol_for_events(events: list):
    trade_volume = 0
    buy_events = list(filter(
        lambda x: get_event_name_from_sig(x['event_sig']) == "FPMMBuy",
        events
    ))

    sell_events = list(filter(
        lambda x: get_event_name_from_sig(x['event_sig']) == "FPMMSell",
        events
    ))

    delta_buy_vol = 0
    delta_sell_vol = 0
    if len(buy_events) > 0:
        delta_buy_vol = float(reduce(
            lambda x, y: x + y,
            map(lambda x: x['investmentAmount'], buy_events)
        ) / pow(10, 6))

    if len(sell_events) > 0:
        delta_sell_vol = float(reduce(
            lambda x, y: x + y,
            map(lambda x: x['returnAmount'], sell_events)
        ) / pow(10, 6))

    trade_volume = delta_sell_vol + delta_buy_vol
    return trade_volume


def get_cumulative_trade_vol(
        results: list
):
    """
    find the cumulative trade vol from buy and sell event logs
    :param results : list of event logs returned from eth_getLogs query
    """
    events = parse_logs(results)

    trade_vol = get_trade_vol_for_events(events)

    return trade_vol
