from exceptions import GenericExitOnSignal
from setproctitle import setproctitle
from uniswap_functions import get_pair_contract_trades_async, get_liquidity_of_each_token_reserve_async
from eth_utils import keccak
from uuid import uuid4
from signal import SIGINT, SIGTERM, SIGQUIT
from message_models import (
    PowerloomCallbackEpoch, PowerloomCallbackProcessMessage, UniswapPairTotalReservesSnapshot,
    EpochBase, UniswapTradesSnapshot
)
from dynaconf import settings
from callback_modules.helpers import AuditProtocolCommandsHelper, CallbackAsyncWorker
from redis_conn import create_redis_conn, REDIS_CONN_CONF
from redis_keys import (
    uniswap_pair_total_reserves_processing_status, uniswap_pair_total_reserves_last_snapshot,
    uniswap_discarded_query_pair_total_reserves_epochs_redis_q_f, uniswap_discarded_query_pair_trade_volume_epochs_redis_q_f,
    uniswap_cb_broadcast_processing_logs_zset, uniswap_failed_query_pair_total_reserves_epochs_redis_q_f,
    uniswap_failed_query_pair_trade_volume_epochs_redis_q_f
)
from pydantic import ValidationError
from helper_functions import AsyncHTTPSessionCache
from aio_pika import ExchangeType, IncomingMessage
from rabbitmq_helpers import RabbitmqSelectLoopInteractor
import queue
import signal
import redis
import asyncio
import aiohttp
import json
import logging
import pika
import time
import multiprocessing


class PairTotalReservesProcessor(CallbackAsyncWorker):
    def __init__(self, name, **kwargs):
        super(PairTotalReservesProcessor, self).__init__(
            name=name,
            rmq_q=f'powerloom-backend-cb-pair_total_reserves-processor:{settings.NAMESPACE}',
            rmq_routing=f'powerloom-backend-callback:{settings.NAMESPACE}.pair_total_reserves_worker.processor',
            **kwargs
        )

    async def _construct_pair_reserves_epoch_snapshot_data(self, msg_obj: PowerloomCallbackProcessMessage, enqueue_on_failure=False):
        max_chain_height = msg_obj.end
        min_chain_height = msg_obj.begin
        enqueue_epoch = False
        epoch_reserves_snapshot_map_token0 = dict()
        epoch_reserves_snapshot_map_token1 = dict()
        max_block_timestamp = int(time.time())  # fallback value, will be set within fetch loop later
        # check for enqueued failed query epochs
        failed_query_epoch = await self._redis_conn.lpop(uniswap_failed_query_pair_total_reserves_epochs_redis_q_f.format(msg_obj.contract))
        queued_epochs = list()
        while failed_query_epoch:
            epoch_broadcast: PowerloomCallbackProcessMessage = PowerloomCallbackProcessMessage.parse_raw(
                failed_query_epoch.decode('utf-8')
            )
            self._logger.info(
                'Found queued epochs that previously failed in RPC query and construction stage for pair total reserves: %s', epoch_broadcast
            )
            queued_epochs.append(epoch_broadcast)
            failed_query_epoch = await self._redis_conn.lpop(
                uniswap_failed_query_pair_total_reserves_epochs_redis_q_f.format(msg_obj.contract))
        queued_epochs.append(msg_obj)
        # check for continuity in epochs before coalescing them
        # assuming the best
        self._logger.info(
            'Attempting to construct a continous epoch for pair total reserves from query failure epochs and current '
            'epoch: %s', queued_epochs
        )
        continuity = True
        for idx, each_epoch in enumerate(queued_epochs):
            if idx == 0:
                continue
            if each_epoch.begin != queued_epochs[idx-1].end + 1:
                continuity = False
                break
        if continuity:
            min_chain_height = queued_epochs[0].begin
            max_chain_height = queued_epochs[-1].end
        # if not continuous, record previous epochs as discarded
        # TODO: can we find a best case scenario to construct a epoch that can be continuous
        else:
            # pop off current epoch added to end of this list
            queued_epochs = queued_epochs[:-1]
            self._logger.info('Recording epochs as discarded during snapshot construction stage for pair total '
                              'reserves processing: %s', queued_epochs)
            [
                self._redis_conn.rpush(uniswap_discarded_query_pair_total_reserves_epochs_redis_q_f.format(msg_obj.contract), x.json())
                for x in queued_epochs
            ]
        for block_num in range(min_chain_height, max_chain_height+1):
            fetch_ts = True if block_num == max_chain_height else False
            try:
                pair_reserve_total = await get_liquidity_of_each_token_reserve_async(
                    loop=asyncio.get_running_loop(),
                    pair_address=msg_obj.contract,
                    block_identifier=block_num,
                    fetch_timestamp=fetch_ts,
                    redis_conn=self._redis_conn
                )
            except:
                # if querying fails, we are going to ensure it is recorded for future processing
                enqueue_epoch = True
                break
            else:
                epoch_reserves_snapshot_map_token0[f'block{block_num}'] = pair_reserve_total['token0']
                epoch_reserves_snapshot_map_token1[f'block{block_num}'] = pair_reserve_total['token1']
                if fetch_ts:
                    if not pair_reserve_total['timestamp']:
                        self._logger.error(
                            f'Could not fetch timestamp for max block height in broadcast {msg_obj} '
                            f'against pair reserves calculation')
                    else:
                        max_block_timestamp = pair_reserve_total['timestamp']
        if enqueue_epoch:
            if enqueue_on_failure:
                # if coalescing was achieved, ensure that is recorded and enqueued as well
                if continuity and queued_epochs:
                    coalesced_broadcast_ids = [x.broadcast_id for x in queued_epochs]
                    coalesced_broadcast_ids.append(msg_obj.broadcast_id)
                    coalesced_epochs = [EpochBase(**{'begin': x.begin, 'end': x.end}) for x in queued_epochs]
                    coalesced_epochs.append(EpochBase(**{'begin': msg_obj.begin, 'end': msg_obj.end}))
                    msg_obj = PowerloomCallbackProcessMessage(
                        begin=queued_epochs[0].begin,
                        end=queued_epochs[-1].end,
                        broadcast_id=msg_obj.broadcast_id,
                        contract=msg_obj.contract,
                        coalesced_broadcast_ids=coalesced_broadcast_ids,
                        coalesced_epochs=coalesced_epochs
                    )
                await self._redis_conn.rpush(
                    uniswap_failed_query_pair_total_reserves_epochs_redis_q_f.format(msg_obj.contract),
                    msg_obj.json()
                )
                self._logger.debug(f'Enqueued epoch broadcast ID {msg_obj.broadcast_id} because reserve query failed: {msg_obj}')
            return None

        pair_total_reserves_snapshot = UniswapPairTotalReservesSnapshot(**{
            'token0Reserves': epoch_reserves_snapshot_map_token0,
            'token1Reserves': epoch_reserves_snapshot_map_token1,
            'chainHeightRange': EpochBase(begin=min_chain_height, end=max_chain_height),
            'timestamp': max_block_timestamp,
            'contract': msg_obj.contract,
            'broadcast_id': msg_obj.broadcast_id
        })
        return pair_total_reserves_snapshot

    async def _construct_trade_volume_epoch_snapshot_data(self, msg_obj: PowerloomCallbackProcessMessage,
                                                           enqueue_on_failure=False):
        max_block_timestamp = int(time.time())  # fallback value, will be set within fetch loop later
        from_block = msg_obj.begin
        to_block = msg_obj.end
        failed_query_epoch = await self._redis_conn.lpop(
            uniswap_failed_query_pair_trade_volume_epochs_redis_q_f.format(msg_obj.contract))
        queued_epochs = list()
        try:
            while failed_query_epoch:
                epoch_broadcast: PowerloomCallbackProcessMessage = PowerloomCallbackProcessMessage.parse_raw(
                    failed_query_epoch.decode('utf-8')
                )
                self._logger.info(
                    'Found queued epochs that previously failed in RPC query and construction stage for trade volume: %s', epoch_broadcast
                )
                queued_epochs.append(epoch_broadcast)
                failed_query_epoch = await self._redis_conn.lpop(
                    uniswap_failed_query_pair_trade_volume_epochs_redis_q_f.format(msg_obj.contract))
            queued_epochs.append(msg_obj)
            # check for continuity in epochs before coalescing them
            # assuming the best
            self._logger.info(
                'Attempting to construct a continuous epoch for trade volume processing from query failure epochs and '
                'current epoch: %s', queued_epochs
            )
            continuity = True
            for idx, each_epoch in enumerate(queued_epochs):
                if idx == 0:
                    continue
                if each_epoch.begin != queued_epochs[idx - 1].end + 1:
                    continuity = False
                    break
            if continuity:
                from_block = queued_epochs[0].begin
                to_block = queued_epochs[-1].end
            # if not continuous, record previous epochs as discarded
            # TODO: can we find a best case scenario to construct a epoch that can be continuous
            else:
                # pop off current epoch added to end of this list
                queued_epochs = queued_epochs[:-1]
                self._logger.info('Recording epochs as discarded during snapshot construction stage for trade volume '
                                'processing: %s', queued_epochs)
                [
                    self._redis_conn.rpush(
                        uniswap_discarded_query_pair_trade_volume_epochs_redis_q_f.format(msg_obj.contract), x.json())
                    for x in queued_epochs
                ]
        except Exception as e:
            # Stroing epoch for next time to be processed or discarded
            await self._redis_conn.rpush(
                uniswap_failed_query_pair_total_reserves_epochs_redis_q_f.format(msg_obj.contract),
                msg_obj.json()
            )
            self._logger.error(f'Error while retrying old failed epoch: {str(e)}')
            return None
        
        try:
            trade_vol_processed_snapshot = await get_pair_contract_trades_async(
                ev_loop=asyncio.get_running_loop(),
                pair_address=msg_obj.contract,
                from_block=from_block,
                to_block=to_block
            )
        except:
            if enqueue_on_failure:
                # if coalescing was achieved, ensure that is recorded and enqueued as well
                if continuity and queued_epochs:
                    coalesced_broadcast_ids = [x.broadcast_id for x in queued_epochs]
                    coalesced_broadcast_ids.append(msg_obj.broadcast_id)
                    coalesced_epochs = [EpochBase(**{'begin': x.begin, 'end': x.end}) for x in queued_epochs]
                    coalesced_epochs.append(EpochBase(**{'begin': msg_obj.begin, 'end': msg_obj.end}))
                    msg_obj = PowerloomCallbackProcessMessage(
                        begin=queued_epochs[0].begin,
                        end=queued_epochs[-1].end,
                        contract=msg_obj.contract,
                        broadcast_id=msg_obj.broadcast_id,
                        coalesced_broadcast_ids=coalesced_broadcast_ids,
                        coalesced_epochs=coalesced_epochs
                    )
                await self._redis_conn.rpush(
                    uniswap_failed_query_pair_total_reserves_epochs_redis_q_f.format(msg_obj.contract),
                    msg_obj.json()
                )
                self._logger.debug(f'Enqueued epoch broadcast ID {msg_obj.broadcast_id} because '
                                   f'trade volume query failed: {msg_obj}')
            return None
        else:
            total_trades_in_usd = 0
            total_fee_in_usd = 0
            total_token0_vol = 0
            total_token1_vol = 0
            final_events_list = list()
            recent_events_logs = list()
            self._logger.debug('Trade volume processed snapshot: %s', trade_vol_processed_snapshot)
            for each_event in trade_vol_processed_snapshot:
                if each_event == 'timestamp':
                    continue
                # self._logger.debug('Event under process: %s | event subdict: %s', each_event, trade_vol_processed_snapshot[each_event])
                # self._logger.debug('event trades: %s', trade_vol_processed_snapshot[each_event]['trades'])
                total_trades_in_usd += trade_vol_processed_snapshot[each_event]['trades']['totalTradesUSD']
                total_fee_in_usd += trade_vol_processed_snapshot[each_event]['trades'].get('totalFeeUSD', 0)
                total_token0_vol += trade_vol_processed_snapshot[each_event]['trades']['token0TradeVolume']
                total_token1_vol += trade_vol_processed_snapshot[each_event]['trades']['token1TradeVolume']
                final_events_list.extend(trade_vol_processed_snapshot[each_event]['logs'])
                recent_events_logs.extend(trade_vol_processed_snapshot[each_event]['trades'].get("recent_transaction_logs", []))
            if not trade_vol_processed_snapshot['timestamp']:
                self._logger.error(
                    f'Could not fetch timestamp for max block height in broadcast {msg_obj} '
                    f'against trade volume calculation')
            else:
                max_block_timestamp = trade_vol_processed_snapshot['timestamp']
            trade_volume_snapshot = UniswapTradesSnapshot(**dict(
                contract=msg_obj.contract,
                broadcast_id=msg_obj.broadcast_id,
                chainHeightRange=EpochBase(begin=msg_obj.begin, end=msg_obj.end),
                timestamp=max_block_timestamp,
                totalTrade=float(f'{total_trades_in_usd: .6f}'),
                totalFee=float(f'{total_fee_in_usd: .6f}'),
                token0TradeVolume=float(f'{total_token0_vol: .6f}'),
                token1TradeVolume=float(f'{total_token1_vol: .6f}'),
                events=final_events_list,
                recent_logs=recent_events_logs
            ))
            return trade_volume_snapshot

    async def _update_broadcast_processing_status(self, broadcast_id, update_state):
        await self._redis_conn.hset(
            uniswap_cb_broadcast_processing_logs_zset.format(self.name),
            broadcast_id,
            json.dumps(update_state)
        )

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        await message.ack()
        self_unique_id = uuid4()
        self._running_callback_tasks[self_unique_id] = asyncio.current_task(asyncio.get_running_loop())
        try:
            msg_obj = PowerloomCallbackProcessMessage.parse_raw(message.body)
        except ValidationError as e:
            self._logger.error(
                'Bad message structure of callback in processor for total pair reserves: %s', e, exc_info=True
            )
            del self._running_callback_tasks[self_unique_id]
            return
        except Exception as e:
            self._logger.error(
                'Unexpected message structure of callback in processor for total pair reserves: %s',
                e,
                exc_info=True
            )
            del self._running_callback_tasks[self_unique_id]
            return
        await self.init_redis_pool()
        self._logger.debug('Got epoch to process for calculating total reserves for pair: %s', msg_obj)

        self._aiohttp_session: aiohttp.ClientSession = await self._aiohttp_session_interface.get_aiohttp_cache
        self._logger.debug('Got aiohttp session cache. Attempting to snapshot total reserves data in epoch %s...', msg_obj)

        pair_total_reserves_epoch_snapshot = await self._construct_pair_reserves_epoch_snapshot_data(msg_obj=msg_obj, enqueue_on_failure=True)
        if not pair_total_reserves_epoch_snapshot:
            self._logger.error('No epoch snapshot to commit. Construction of snapshot failed for %s', msg_obj)
            update_log = {
                'worker': self._unique_id,
                'update': {
                    'action': 'PairReserves.SnapshotBuild',
                    'info': {
                        'msg': msg_obj.dict(),
                        'status': 'Failed'
                    }
                }
            }

            self._redis_conn.zadd(
                key=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                score=int(time.time()),
                member=json.dumps(update_log)
            )
        else:
            update_log = {
                'worker': self._unique_id,
                'update': {
                    'action': 'PairReserves.SnapshotBuild',
                    'info': {
                        'msg': msg_obj.dict(),
                        'status': 'Success',
                        'snapshot': pair_total_reserves_epoch_snapshot.dict()
                    }
                }
            }

            self._redis_conn.zadd(
                key=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                score=int(time.time()),
                member=json.dumps(update_log)
            )
            # TODO: should we attach previous total reserves epoch from cache?
            await AuditProtocolCommandsHelper.set_diff_rule_for_pair_reserves(
                pair_contract_address=pair_total_reserves_epoch_snapshot.contract,
                stream='pair_total_reserves',
                session=self._aiohttp_session
            )
            payload = pair_total_reserves_epoch_snapshot.dict()
            try:
                r = await AuditProtocolCommandsHelper.commit_payload(
                    pair_contract_address=pair_total_reserves_epoch_snapshot.contract,
                    stream='pair_total_reserves',
                    report_payload=payload,
                    session=self._aiohttp_session
                )
            except Exception as e:
                self._logger.error('Exception committing snapshot to audit protocol: %s | dump: %s',
                                   pair_total_reserves_epoch_snapshot, e, exc_info=True)
                update_log = {
                    'worker': self._unique_id,
                    'update': {
                        'action': 'PairReserves.SnapshotCommit',
                        'info': {
                            'msg': payload,
                            'status': 'Failed',
                            'exception': e
                        }
                    }
                }

                self._redis_conn.zadd(
                    key=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                    score=int(time.time()),
                    member=json.dumps(update_log)
                )
            else:
                if type(r) is dict and 'message' in r.keys():
                    self._logger.error('Error committing pair token reserves snapshot to audit protocol: %s | Helper Response: %s',
                                       pair_total_reserves_epoch_snapshot, r)
                    update_log = {
                        'worker': self._unique_id,
                        'update': {
                            'action': 'PairReserves.SnapshotCommit',
                            'info': {
                                'msg': payload,
                                'status': 'Failed',
                                'error': r
                            }
                        }
                    }

                    self._redis_conn.zadd(
                        key=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                        score=int(time.time()),
                        member=json.dumps(update_log)
                    )
                else:
                    self._logger.debug('Sent snapshot to audit protocol: %s | Helper Response: %s', pair_total_reserves_epoch_snapshot, r)
                    update_log = {
                        'worker': self._unique_id,
                        'update': {
                            'action': 'PairReserves.SnapshotCommit',
                            'info': {
                                'msg': payload,
                                'status': 'Success',
                                'response': r
                            }
                        }
                    }

                    self._redis_conn.zadd(
                        key=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                        score=int(time.time()),
                        member=json.dumps(update_log)
                    )

        # prepare trade volume snapshot
        trade_vol_epoch_snapshot = await self._construct_trade_volume_epoch_snapshot_data(
            msg_obj=msg_obj, enqueue_on_failure=True
        )
        if not trade_vol_epoch_snapshot:
            self._logger.error('No epoch snapshot to commit for trade volume. Construction of snapshot failed for %s', msg_obj)
            update_log = {
                'worker': self._unique_id,
                'update': {
                    'action': 'TradeVolume.SnapshotBuild',
                    'info': {
                        'msg': msg_obj.dict(),
                        'status': 'Failed'
                    }
                }
            }

            self._redis_conn.zadd(
                key=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                score=int(time.time()),
                member=json.dumps(update_log)
            )
        else:
            update_log = {
                'worker': self._unique_id,
                'update': {
                    'action': 'TradeVolume.SnapshotBuild',
                    'info': {
                        'msg': msg_obj.dict(),
                        'status': 'Success',
                        'snapshot': trade_vol_epoch_snapshot.dict()
                    }
                }
            }

            self._redis_conn.zadd(
                key=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                score=int(time.time()),
                member=json.dumps(update_log)
            )
            # TODO: should we attach previous trade volume epoch from cache?
            await AuditProtocolCommandsHelper.set_diff_rule_for_trade_volume(
                pair_contract_address=msg_obj.contract,
                stream='trade_volume',
                session=self._aiohttp_session
            )
            payload = trade_vol_epoch_snapshot.dict()
            try:
                r = await AuditProtocolCommandsHelper.commit_payload(
                    pair_contract_address=msg_obj.contract,
                    stream='trade_volume',
                    report_payload=payload,
                    session=self._aiohttp_session
                )
            except Exception as e:
                self._logger.error('Exception committing snapshot to audit protocol: %s | dump: %s',
                                   pair_total_reserves_epoch_snapshot, e, exc_info=True)
                update_log = {
                    'worker': self._unique_id,
                    'update': {
                        'action': 'TradeVolume.SnapshotCommit',
                        'info': {
                            'msg': payload,
                            'status': 'Failed',
                            'exception': e
                        }
                    }
                }

                self._redis_conn.zadd(
                    key=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                    score=int(time.time()),
                    member=json.dumps(update_log)
                )
            else:
                if type(r) is dict and 'message' in r.keys():
                    self._logger.error('Error committing trade volume snapshot to audit protocol: %s | Helper Response: %s',
                                       trade_vol_epoch_snapshot, r)
                    update_log = {
                        'worker': self._unique_id,
                        'update': {
                            'action': 'TradeVolume.SnapshotCommit',
                            'info': {
                                'msg': payload,
                                'status': 'Failed',
                                'error': r
                            }
                        }
                    }

                    self._redis_conn.zadd(
                        key=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                        score=int(time.time()),
                        member=json.dumps(update_log)
                    )
                else:
                    self._logger.debug('Sent snapshot to audit protocol: %s | Helper Response: %s', trade_vol_epoch_snapshot, r)
                    update_log = {
                        'worker': self._unique_id,
                        'update': {
                            'action': 'TradeVolume.SnapshotCommit',
                            'info': {
                                'msg': payload,
                                'status': 'Success',
                                'response': r
                            }
                        }
                    }

                    self._redis_conn.zadd(
                        key=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                        score=int(time.time()),
                        member=json.dumps(update_log)
                    )
        del self._running_callback_tasks[self_unique_id]

    def run(self):
        # setup_loguru_intercept()
        setproctitle(self.name)
        self._aiohttp_session_interface = AsyncHTTPSessionCache()
        # self._logger.debug('Launching epochs summation actor for total reserves of pairs...')
        super(PairTotalReservesProcessor, self).run()


class PairTotalReservesProcessorDistributor(multiprocessing.Process):
    def __init__(self, name, **kwargs):
        super(PairTotalReservesProcessorDistributor, self).__init__(name=name, **kwargs)
        self._unique_id = f'{name}-' + keccak(text=str(uuid4())).hex()[:8]
        self._q = queue.Queue()
        self._rabbitmq_interactor = None
        self._shutdown_initiated = False
        # logger.add(
        #     sink='logs/' + self._unique_id + '_{time}.log', rotation='20MB', retention=20, compression='gz'
        # )
        # setup_loguru_intercept()

    def _distribute_callbacks(self, dont_use_ch, method, properties, body):
        self._rabbitmq_interactor._channel.basic_ack(delivery_tag=method.delivery_tag)
        # following check avoids processing messages meant for routing keys for sub workers
        # for eg: 'powerloom-backend-callback.pair_total_reserves.seeder'
        if 'pair_total_reserves' not in method.routing_key or method.routing_key.split('.')[1] != 'pair_total_reserves':
            return
        self._logger.debug('Got processed epoch to distribute among processors for total reserves of a pair: %s', body)
        try:
            msg_obj: PowerloomCallbackEpoch = PowerloomCallbackEpoch.parse_raw(body)
        except ValidationError:
            self._logger.error('Bad message structure of epoch callback', exc_info=True)
            return
        except Exception as e:
            self._logger.error('Unexpected message format of epoch callback', exc_info=True)
            return

        for contract in msg_obj.contracts:
            contract = contract.lower()
            pair_total_reserves_process_unit = PowerloomCallbackProcessMessage(
                begin=msg_obj.begin,
                end=msg_obj.end,
                contract=contract,
                broadcast_id=msg_obj.broadcast_id
            )
            self._rabbitmq_interactor.enqueue_msg_delivery(
                exchange=f'{settings.RABBITMQ.SETUP.CALLBACKS.EXCHANGE}.subtopics:{settings.NAMESPACE}',
                routing_key=f'powerloom-backend-callback:{settings.NAMESPACE}.pair_total_reserves_worker.processor',
                msg_body=pair_total_reserves_process_unit.json()
            )
            self._logger.debug(f'Sent out epoch to be processed by worker to calculate total reserves for pair contract: {pair_total_reserves_process_unit}')
        update_log = {
            'worker': self._unique_id,
            'update': {
                'action': 'RabbitMQ.Publish',
                'info': {
                    'routing_key': f'powerloom-backend-callback:{settings.NAMESPACE}.pair_total_reserves_worker.processor',
                    'exchange': f'{settings.RABBITMQ.SETUP.CALLBACKS.EXCHANGE}.subtopics:{settings.NAMESPACE}',
                    'msg': msg_obj.dict()
                }
            }
        }
        with create_redis_conn(self._connection_pool) as r:
            r.zadd(
                uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                {json.dumps(update_log): int(time.time())}
            )

    def _exit_signal_handler(self, signum, sigframe):
        if signum in [SIGINT, SIGTERM, SIGQUIT] and not self._shutdown_initiated:
            self._shutdown_initiated = True
            self._rabbitmq_interactor.stop()

    def run(self):
        setproctitle(self.name)
        for signame in [SIGINT, SIGTERM, SIGQUIT]:
            signal.signal(signame, self._exit_signal_handler)
        # logging.config.dictConfig(config_logger_with_namespace('PowerLoom|Callbacks|TradeVolumeProcessDistributor'))
        self._logger = logging.getLogger('PowerLoom|Callbacks|PairTotalReservesProcessDistributor')
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers = [
            logging.handlers.SocketHandler(host='localhost', port=logging.handlers.DEFAULT_TCP_LOGGING_PORT)]
        self._connection_pool = redis.BlockingConnectionPool(**REDIS_CONN_CONF)
        queue_name = f'powerloom-backend-cb:{settings.NAMESPACE}'
        self._rabbitmq_interactor: RabbitmqSelectLoopInteractor = RabbitmqSelectLoopInteractor(
            consume_queue_name=queue_name,
            consume_callback=self._distribute_callbacks,
            consumer_worker_name='PowerLoom|Callbacks|PairTotalReservesProcessDistributor'
        )
        # self.rabbitmq_interactor.start_publishing()
        self._logger.debug('Starting RabbitMQ consumer on queue %s', queue_name)
        self._rabbitmq_interactor.run()
