from httpx import AsyncClient
from setproctitle import setproctitle
from uniswap_functions import (
    load_rate_limiter_scripts, get_pair_trade_volume, get_pair_reserves,
    warm_up_cache_for_snapshot_constructors
)
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
import json
import logging
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
        self._rate_limiting_lua_scripts = dict()

    async def _warm_up_cache_for_epoch_data(self, msg_obj: PowerloomCallbackProcessMessage):
        """
            Function to warm up the cache which is used across all snapshot constructors
            and/or for internal helper functions.
        """
        try:
            max_chain_height = msg_obj.end
            min_chain_height = msg_obj.begin

            await warm_up_cache_for_snapshot_constructors(
                loop=asyncio.get_running_loop(),
                from_block=min_chain_height,
                to_block=max_chain_height,
                redis_conn=self._redis_conn,
                rate_limit_lua_script_shas=self._rate_limiting_lua_scripts
            )
        except Exception as exc:
            self._logger.warning(f"There was an error while warming-up cache for epoch data. error_msg: {exc}")
            pass

        return None

    async def _construct_pair_reserves_epoch_snapshot_data(self, msg_obj: PowerloomCallbackProcessMessage, enqueue_on_failure=False):
        max_chain_height = msg_obj.end
        min_chain_height = msg_obj.begin
        enqueue_epoch = False
        epoch_reserves_snapshot_map_token0 = dict()
        epoch_reserves_snapshot_map_token1 = dict()
        epoch_usd_reserves_snapshot_map_token0 = dict()
        epoch_usd_reserves_snapshot_map_token1 = dict()
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
            'Attempting to construct a continuous epoch for pair total reserves from query failure epochs and current '
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
            for x in queued_epochs:
                await self._redis_conn.rpush(uniswap_discarded_query_pair_total_reserves_epochs_redis_q_f.format(msg_obj.contract), x.json())
        
        try:
            web3_provider = {}
            # set RPC archive node if there are multiple epochs enqueued
            if max_chain_height - (min_chain_height - 1) > settings.RPC.FORCE_ARCHIVE_BLOCKS:
                web3_provider = {"force_archive": True}

            pair_reserve_total = await get_pair_reserves(
                loop=asyncio.get_running_loop(),
                rate_limit_lua_script_shas=self._rate_limiting_lua_scripts,
                pair_address=msg_obj.contract,
                from_block=min_chain_height,
                to_block=max_chain_height,
                redis_conn=self._redis_conn,
                fetch_timestamp=True,
                web3_provider=web3_provider
            )
        except Exception as exc:
            self._logger.error(f"Pair-Reserves function failed for epoch: {min_chain_height}-{max_chain_height} | error_msg:{exc}")
            # if querying fails, we are going to ensure it is recorded for future processing
            enqueue_epoch = True
        else:
            for block_num in range(min_chain_height, max_chain_height+1):
                
                block_pair_total_reserves = pair_reserve_total.get(block_num)
                fetch_ts = True if block_num == max_chain_height else False

                epoch_reserves_snapshot_map_token0[f'block{block_num}'] = block_pair_total_reserves['token0']
                epoch_reserves_snapshot_map_token1[f'block{block_num}'] = block_pair_total_reserves['token1']
                epoch_usd_reserves_snapshot_map_token0[f'block{block_num}'] = block_pair_total_reserves['token0USD']
                epoch_usd_reserves_snapshot_map_token1[f'block{block_num}'] = block_pair_total_reserves['token1USD']
                
                if fetch_ts:
                    if not block_pair_total_reserves.get('timestamp', None):
                        self._logger.error(
                            f'Could not fetch timestamp for max block height in broadcast {msg_obj} '
                            f'against pair reserves calculation')
                    else:
                        max_block_timestamp = block_pair_total_reserves.get('timestamp')
        
        if enqueue_epoch:
            if enqueue_on_failure:
                # if coalescing was achieved, ensure that is recorded and enqueued as well
                if continuity and queued_epochs:
                    coalesced_broadcast_ids = [x.broadcast_id for x in queued_epochs]
                    #coalesced_broadcast_ids.append(msg_obj.broadcast_id)
                    coalesced_epochs = [EpochBase(**{'begin': x.begin, 'end': x.end}) for x in queued_epochs]
                    #coalesced_epochs.append(EpochBase(**{'begin': msg_obj.begin, 'end': msg_obj.end}))
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
            'token0ReservesUSD': epoch_usd_reserves_snapshot_map_token0,
            'token1ReservesUSD': epoch_usd_reserves_snapshot_map_token1,
            'chainHeightRange': EpochBase(begin=min_chain_height, end=max_chain_height),
            'timestamp': max_block_timestamp,
            'contract': msg_obj.contract
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
                for x in queued_epochs:
                    await self._redis_conn.rpush(uniswap_discarded_query_pair_trade_volume_epochs_redis_q_f.format(msg_obj.contract), x.json())

        except Exception as e:
            # Stroing epoch for next time to be processed or discarded
            await self._redis_conn.rpush(
                uniswap_failed_query_pair_trade_volume_epochs_redis_q_f.format(msg_obj.contract),
                msg_obj.json()
            )
            self._logger.error(f'Error while retrying old failed epoch: {str(e)}')
            return None
        
        try:
            # set RPC archive node if there are multiple epoch enqueued
            web3_provider = {}
            if to_block - (from_block - 1) > settings.RPC.FORCE_ARCHIVE_BLOCKS:
                web3_provider = {"force_archive": True}

            trade_vol_processed_snapshot = await get_pair_trade_volume(
                ev_loop=asyncio.get_running_loop(),
                rate_limit_lua_script_shas=self._rate_limiting_lua_scripts,
                pair_address=msg_obj.contract,
                from_block=from_block,
                to_block=to_block,
                redis_conn=self._redis_conn,
                web3_provider=web3_provider
            )
        
            total_trades_in_usd = 0
            total_fee_in_usd = 0
            total_token0_vol = 0
            total_token1_vol = 0
            total_token0_vol_usd = 0
            total_token1_vol_usd = 0
            recent_events_logs = list()
            self._logger.debug('Trade volume processed snapshot: %s', trade_vol_processed_snapshot)
            
            #Set effective trade volume at top level
            total_trades_in_usd = trade_vol_processed_snapshot['Trades']['totalTradesUSD']
            total_fee_in_usd = trade_vol_processed_snapshot['Trades']['totalFeeUSD']
            total_token0_vol = trade_vol_processed_snapshot['Trades']['token0TradeVolume']
            total_token1_vol = trade_vol_processed_snapshot['Trades']['token1TradeVolume']
            total_token0_vol_usd = trade_vol_processed_snapshot['Trades']['token0TradeVolumeUSD']
            total_token1_vol_usd = trade_vol_processed_snapshot['Trades']['token1TradeVolumeUSD']


            if not trade_vol_processed_snapshot.get('timestamp', None):
                self._logger.error(
                    f'Could not fetch timestamp for max block height in broadcast {msg_obj} '
                    f'against trade volume calculation')
            else:
                max_block_timestamp = trade_vol_processed_snapshot.get('timestamp')
                trade_vol_processed_snapshot.pop('timestamp', None)
            trade_volume_snapshot = UniswapTradesSnapshot(**dict(
                contract=msg_obj.contract,
                chainHeightRange=EpochBase(begin=from_block, end=to_block),
                timestamp=max_block_timestamp,
                totalTrade=float(f'{total_trades_in_usd: .6f}'),
                totalFee=float(f'{total_fee_in_usd: .6f}'),
                token0TradeVolume=float(f'{total_token0_vol: .6f}'),
                token1TradeVolume=float(f'{total_token1_vol: .6f}'),
                token0TradeVolumeUSD=float(f'{total_token0_vol_usd: .6f}'),
                token1TradeVolumeUSD=float(f'{total_token1_vol_usd: .6f}'),
                events=trade_vol_processed_snapshot
            ))
            return trade_volume_snapshot

        except Exception as e:
            self._logger.error(f"Pair Trade-volume function failed for epoch: {from_block}-{to_block} | error_msg:{e}")
            
            if enqueue_on_failure:
                # if coalescing was achieved, ensure that is recorded and enqueued as well
                if continuity and queued_epochs:
                    coalesced_broadcast_ids = [x.broadcast_id for x in queued_epochs]
                    #coalesced_broadcast_ids.append(msg_obj.broadcast_id)
                    coalesced_epochs = [EpochBase(**{'begin': x.begin, 'end': x.end}) for x in queued_epochs]
                    #coalesced_epochs.append(EpochBase(**{'begin': msg_obj.begin, 'end': msg_obj.end}))
                    msg_obj = PowerloomCallbackProcessMessage(
                        begin=queued_epochs[0].begin,
                        end=queued_epochs[-1].end,
                        contract=msg_obj.contract,
                        broadcast_id=msg_obj.broadcast_id,
                        coalesced_broadcast_ids=coalesced_broadcast_ids,
                        coalesced_epochs=coalesced_epochs
                    )
                await self._redis_conn.rpush(
                    uniswap_failed_query_pair_trade_volume_epochs_redis_q_f.format(msg_obj.contract),
                    msg_obj.json()
                )
                self._logger.error(f'Enqueued epoch broadcast ID {msg_obj.broadcast_id} because '
                                   f'trade volume query failed: {msg_obj}: {e}', exc_info=True)
            return None

    async def _update_broadcast_processing_status(self, broadcast_id, update_state):
        await self._redis_conn.hset(
            uniswap_cb_broadcast_processing_logs_zset.format(self.name),
            broadcast_id,
            json.dumps(update_state)
        )

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        await message.ack()
        self_unique_id = str(uuid4())
        # cur_task.add_done_callback()
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
        cur_task: asyncio.Task = asyncio.current_task(asyncio.get_running_loop())
        cur_task.set_name(f'aio_pika.consumer|PairTotalReservesProcessor|{msg_obj.contract}')
        self._running_callback_tasks[self_unique_id] = cur_task

        await self.init_redis_pool()
        if not self._rate_limiting_lua_scripts:
            self._rate_limiting_lua_scripts = await load_rate_limiter_scripts(self._redis_conn)
        self._logger.debug('Got epoch to process for calculating total reserves for pair: %s', msg_obj)

        self._httpx_session_client: AsyncClient = await self._aiohttp_session_interface.get_httpx_session_client
        self._logger.debug('Got aiohttp session cache. Attempting to snapshot total reserves data in epoch %s...', msg_obj)


        # warm-up cache before constructing snapshots
        await self._warm_up_cache_for_epoch_data(msg_obj=msg_obj)


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

            await self._redis_conn.zadd(
                name=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                mapping={json.dumps(update_log): int(time.time())}
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

            await self._redis_conn.zadd(
                name=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                mapping={json.dumps(update_log): int(time.time())}
            )
            # TODO: should we attach previous total reserves epoch from cache?
            await AuditProtocolCommandsHelper.set_diff_rule_for_pair_reserves(
                pair_contract_address=pair_total_reserves_epoch_snapshot.contract,
                stream='pair_total_reserves',
                session=self._httpx_session_client,
                redis_conn=self._redis_conn
            )
            payload = pair_total_reserves_epoch_snapshot.dict()
            try:
                r = await AuditProtocolCommandsHelper.commit_payload(
                    pair_contract_address=pair_total_reserves_epoch_snapshot.contract,
                    stream='pair_total_reserves',
                    report_payload=payload,
                    session=self._httpx_session_client
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

                await self._redis_conn.zadd(
                    name=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                    mapping={json.dumps(update_log): int(time.time())}
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

                    await self._redis_conn.zadd(
                        name=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                        mapping={json.dumps(update_log): int(time.time())}
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

                    await self._redis_conn.zadd(
                        name=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                        mapping={json.dumps(update_log): int(time.time())}
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

            await self._redis_conn.zadd(
                name=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                mapping={json.dumps(update_log): int(time.time())}
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

            await self._redis_conn.zadd(
                name=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                mapping={json.dumps(update_log): int(time.time())}
            )
            # TODO: should we attach previous trade volume epoch from cache?
            await AuditProtocolCommandsHelper.set_diff_rule_for_trade_volume(
                pair_contract_address=msg_obj.contract,
                stream='trade_volume',
                session=self._httpx_session_client,
                redis_conn=self._redis_conn
            )
            payload = trade_vol_epoch_snapshot.dict()
            try:
                r = await AuditProtocolCommandsHelper.commit_payload(
                    pair_contract_address=msg_obj.contract,
                    stream='trade_volume',
                    report_payload=payload,
                    session=self._httpx_session_client
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

                await self._redis_conn.zadd(
                    name=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                    mapping={json.dumps(update_log): int(time.time())}
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

                    await self._redis_conn.zadd(
                        name=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                        mapping={json.dumps(update_log): int(time.time())}
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

                    await self._redis_conn.zadd(
                        name=uniswap_cb_broadcast_processing_logs_zset.format(msg_obj.broadcast_id),
                        mapping={json.dumps(update_log): int(time.time())}
                    )
        del self._running_callback_tasks[self_unique_id]

    def run(self):
        setproctitle(self.name)
        # setup_loguru_intercept()
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
        self._rabbitmq_interactor._channel.basic_ack(delivery_tag=method.delivery_tag)

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
        setproctitle(self.name)
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers = [
            logging.handlers.SocketHandler(host=settings.get('LOGGING_SERVER.HOST','localhost'),
            port=settings.get('LOGGING_SERVER.PORT',logging.handlers.DEFAULT_TCP_LOGGING_PORT))]
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
