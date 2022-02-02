import asyncio

import aiohttp

from init_rabbitmq import create_rabbitmq_conn
from setproctitle import setproctitle
from uniswap_functions import get_liquidity_of_each_token_reserve, async_get_liquidity_of_each_token_reserve
from typing import List
from functools import reduce
from message_models import (
    PowerloomCallbackEpoch, PowerloomCallbackProcessMessage, UniswapEpochPairTotalReserves,
    EpochBase
)
from dynaconf import settings
from callback_modules.helpers import AuditProtocolCommandsHelper, CallbackAsyncWorker, get_cumulative_trade_vol
from redis_keys import (
    uniswap_pair_total_reserves_processing_status, uniswap_pair_total_reserves_last_snapshot,
    eth_log_request_data_f, uniswap_failed_pair_total_reserves_epochs_redis_q_f
)
from pydantic import ValidationError
from functools import wraps
from helper_functions import AsyncHTTPSessionCache
from aio_pika import ExchangeType, IncomingMessage
import aioredis
import logging
import pika
import aio_pika
import time
import json
import multiprocessing
import requests


class PairTotalReservesProcessor(CallbackAsyncWorker):
    def __init__(self, name, **kwargs):
        super(PairTotalReservesProcessor, self).__init__(
            name=name,
            name_prefix='PairTotalReservesProcessor',
            rmq_q=f'powerloom-backend-cb-pair_total_reserves-processor:{settings.NAMESPACE}',
            rmq_routing=f'powerloom-backend-callback:{settings.NAMESPACE}.pair_total_reserves_worker.processor',
            **kwargs
        )

    async def _construct_epoch_snapshot_data(self, msg_obj: PowerloomCallbackProcessMessage, enqueue_on_failure=False):
        max_chain_height = msg_obj.end
        min_chain_height = msg_obj.begin
        enqueue_epoch = False
        epoch_reserves_snapshot_map = dict()
        for block_num in range(min_chain_height, max_chain_height+1):
            # TODO: support querying of reserves at this `block_num`
            try:
                pair_reserve_total = await async_get_liquidity_of_each_token_reserve(
                    loop=asyncio.get_event_loop(),
                    pair_address=msg_obj.contract,
                    block_identifier=block_num
                )
            except:
                # if querying fails, we are going to ensure it is recorded for future processing
                enqueue_epoch = True
                break
            else:
                epoch_reserves_snapshot_map[f'block{block_num}'] = pair_reserve_total
        if enqueue_epoch:
            if enqueue_on_failure:
                await self._redis_conn.rpush(
                    uniswap_failed_pair_total_reserves_epochs_redis_q_f.format(msg_obj.contract),
                    msg_obj.json()
                )
                self._logger.debug(f'Enqueued epoch broadcast ID {msg_obj.broadcast_id} because reserve query failed: {msg_obj}')
            return None

        pair_total_reserves_snapshot = UniswapEpochPairTotalReserves(**{
            'totalReserves': epoch_reserves_snapshot_map,
            'chainHeightRange': EpochBase(begin=min_chain_height, end=max_chain_height),
            'timestamp': float(f'{time.time(): .4f}'),
            'contract': msg_obj.contract,
            'broadcast_id': msg_obj.broadcast_id
        })
        return pair_total_reserves_snapshot

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        await message.ack()
        try:
            msg_obj = PowerloomCallbackProcessMessage.parse_raw(message.body)
        except ValidationError as e:
            self._logger.error(
                'Bad message structure of callback in processor for total pair reserves: %s', e, exc_info=True
            )
            return
        except Exception as e:
            self._logger.error(
                'Unexpected message structure of callback in processor for total pair reserves: %s',
                e,
                exc_info=True
            )
            return
        await self.init_redis_pool()
        self._logger.debug('Got epoch to process for calculating total reserves for pair: %s', msg_obj)

        self._aiohttp_session: aiohttp.ClientSession = await self._aiohttp_session_interface.get_aiohttp_cache
        self._logger.debug('Got aiohttp session cache. Now sending call to trade volume seeding function...')

        pair_total_reserves_epoch_snapshot = await self._construct_epoch_snapshot_data(msg_obj=msg_obj, enqueue_on_failure=True)
        if not pair_total_reserves_epoch_snapshot:
            return
        # TODO: should we attach previous total reserves epoch from cache?
        await AuditProtocolCommandsHelper.set_diff_rule_for_pair_reserves(
            pair_contract_address=pair_total_reserves_epoch_snapshot.contract,
            stream='pair_total_reserves'
        )
        payload = pair_total_reserves_epoch_snapshot.dict()
        # TODO: check response returned
        await AuditProtocolCommandsHelper.commit_payload(
            pair_contract_address=pair_total_reserves_epoch_snapshot.contract,
            stream='pair_total_reserves',
            report_payload=payload,
            session=self._aiohttp_session
        )
        # TODO: update last snapshot in cache
        #  TODO: update processing status in cache?
        # await self._redis_conn.set(uniswap_pair_total_reserves_processing_status.format(pair_total_reserves_epoch_data.contract),
        #                            json.dumps(
        #                                {
        #                                    'status': 'updatedCache',
        #                                    'data': {
        #                                        'prevBase': prev_trade_vol_obj,
        #                                        'extended': {
        #                                            'buys': trades_snapshot.buys,
        #                                            'sells': trades_snapshot.sells
        #                                        },
        #                                        'newBase': new_trade_vol
        #                                    }
        #                                }
        #                            ))

    def run(self):
        # setup_loguru_intercept()
        self._aiohttp_session_interface = AsyncHTTPSessionCache()
        self._logger.debug('Launching epochs summation actor for total reserves of pairs...')
        super(PairTotalReservesProcessor, self).run()


class PairTotalReservesProcessorDistributor(multiprocessing.Process):
    def __init__(self, name, **kwargs):
        super(PairTotalReservesProcessorDistributor, self).__init__(name=name, **kwargs)
        setproctitle(self.name)
        # logger.add(
        #     sink='logs/' + self._unique_id + '_{time}.log', rotation='20MB', retention=20, compression='gz'
        # )
        # setup_loguru_intercept()

    def _distribute_callbacks(self, ch, method, properties, body):
        ch.basic_ack(delivery_tag=method.delivery_tag)
        # following check avoids processing messages meant for routing keys for sub workers
        # for eg: 'powerloom-backend-callback.pair_total_reserves.seeder'
        if 'pair_total_reserves' not in method.routing_key or method.routing_key.split('.')[1] != 'pair_total_reserves':
            return
        self._logger.debug('Got processed epoch to distribute among processors for total reserves of a pair: %s', body)
        try:
            msg_obj = PowerloomCallbackEpoch.parse_raw(body)
        except ValidationError:
            self._logger.error('Bad message structure of epoch callback', exc_info=True)
            return
        except Exception as e:
            self._logger.error('Unexpected message format of epoch callback', exc_info=True)
            return
        for contract in msg_obj.contracts:
            contract = contract.lower()
            trade_vol_process_unit = PowerloomCallbackProcessMessage(
                begin=msg_obj.begin,
                end=msg_obj.end,
                contract=contract,
                broadcast_id=msg_obj.broadcast_id
            )
            ch.basic_publish(
                exchange=f'{settings.RABBITMQ.SETUP.CALLBACKS.EXCHANGE}.subtopics:{settings.NAMESPACE}',
                routing_key=f'powerloom-backend-callback:{settings.NAMESPACE}.pair_total_reserves.processor',
                body=trade_vol_process_unit.json().encode('utf-8'),
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type='text/plain',
                    content_encoding='utf-8'
                ),
                mandatory=True
            )
            self._logger.debug(f'Sent out epoch to be processed by worker to calculate total reserves: {trade_vol_process_unit}')

    def run(self):
        # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|Callbacks|TradeVolumeProcessDistributor'))
        self._logger = logging.getLogger('PowerLoom|Callbacks|TradeVolumeProcessDistributor')
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers = [
            logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]
        c = create_rabbitmq_conn()
        ch = c.channel()

        queue_name = f'powerloom-backend-cb:{settings.NAMESPACE}'
        ch.basic_qos(prefetch_count=1)
        ch.basic_consume(
            queue=queue_name,
            on_message_callback=self._distribute_callbacks,
            auto_ack=False
        )
        try:
            self._logger.debug('Starting RabbitMQ consumer on queue %s', queue_name)
            ch.start_consuming()
        except Exception as e:
            self._logger.error('Exception while running consumer on queue %s: %s', queue_name, e)
        finally:
            self._logger.error('Attempting to close residual RabbitMQ connections and channels')
            try:
                ch.close()
                c.close()
            except:
                pass
