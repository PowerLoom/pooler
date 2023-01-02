from typing import Optional, List, Awaitable, Callable, Dict, Tuple, Union
from httpx import AsyncClient, AsyncHTTPTransport, Timeout, Limits
from setproctitle import setproctitle
from callback_modules.uniswap.core import (
    get_pair_reserves, get_pair_trade_volume,
    warm_up_cache_for_snapshot_constructors
)
from rate_limiter import load_rate_limiter_scripts
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
    uniswap_discarded_query_pair_total_reserves_epochs_redis_q_f,
    uniswap_discarded_query_pair_trade_volume_epochs_redis_q_f,
    uniswap_cb_broadcast_processing_logs_zset, uniswap_failed_query_pair_total_reserves_epochs_redis_q_f,
    uniswap_failed_query_pair_trade_volume_epochs_redis_q_f
)
from pydantic import ValidationError, BaseModel as CustomDataModel
from .data_models import PayloadCommitAPIRequest, SourceChainDetails
from aio_pika import ExchangeType, IncomingMessage, Message, DeliveryMode
from rabbitmq_helpers import RabbitmqSelectLoopInteractor
import queue
import signal
import redis
import asyncio
import json
import os
import logging
import time
import multiprocessing
from default_logger import logger

SETTINGS_ENV = os.getenv('ENV_FOR_DYNACONF', 'development')


class PairTotalReservesProcessor(CallbackAsyncWorker):
    def __init__(self, name, **kwargs):
        super(PairTotalReservesProcessor, self).__init__(
            name=name,
            rmq_q=f'powerloom-backend-cb-pair_total_reserves-processor:{settings.NAMESPACE}:{settings.INSTANCE_ID}',
            rmq_routing=f'powerloom-backend-callback:{settings.NAMESPACE}:{settings.INSTANCE_ID}.pair_total_reserves_worker.processor',
            **kwargs
        )
        self._rate_limiting_lua_scripts = dict()
        self._async_transport = AsyncHTTPTransport(
            limits=Limits(max_connections=100, max_keepalive_connections=50, keepalive_expiry=None)
        )
        self._client = AsyncClient(
            # base_url=self._base_url,
            timeout=Timeout(timeout=5.0),
            follow_redirects=False,
            transport=self._async_transport
        )

    async def _fetch_token_reserves_on_chain(
            self,
            min_chain_height,
            max_chain_height,
            data_source_contract_address
    ):
        epoch_reserves_snapshot_map_token0 = dict()
        epoch_reserves_snapshot_map_token1 = dict()
        epoch_usd_reserves_snapshot_map_token0 = dict()
        epoch_usd_reserves_snapshot_map_token1 = dict()
        max_block_timestamp = int(time.time())
        try:
            # TODO: web3 object should be available within callback worker instance
            #  instead of being a global object in uniswap functions module. Not a good design pattern.
            pair_reserve_total = await get_pair_reserves(
                loop=asyncio.get_running_loop(),
                rate_limit_lua_script_shas=self._rate_limiting_lua_scripts,
                pair_address=data_source_contract_address,
                from_block=min_chain_height,
                to_block=max_chain_height,
                redis_conn=self._redis_conn,
                fetch_timestamp=True
            )
        except Exception as exc:
            self._logger.error(
                f"Pair-Reserves function failed for epoch: {min_chain_height}-{max_chain_height} | error_msg:{exc}")
            # if querying fails, we are going to ensure it is recorded for future processing
            return None
        else:
            for block_num in range(min_chain_height, max_chain_height + 1):

                block_pair_total_reserves = pair_reserve_total.get(block_num)
                fetch_ts = True if block_num == max_chain_height else False

                epoch_reserves_snapshot_map_token0[f'block{block_num}'] = block_pair_total_reserves['token0']
                epoch_reserves_snapshot_map_token1[f'block{block_num}'] = block_pair_total_reserves['token1']
                epoch_usd_reserves_snapshot_map_token0[f'block{block_num}'] = block_pair_total_reserves['token0USD']
                epoch_usd_reserves_snapshot_map_token1[f'block{block_num}'] = block_pair_total_reserves['token1USD']

                if fetch_ts:
                    if not block_pair_total_reserves.get('timestamp', None):
                        self._logger.error(
                            'Could not fetch timestamp against max block height in epoch %s - %s'
                            'to calculate pair reserves for contract %s. '
                            'Using current time stamp for snapshot construction',
                            data_source_contract_address, min_chain_height, max_chain_height
                        )
                    else:
                        max_block_timestamp = block_pair_total_reserves.get('timestamp')
            pair_total_reserves_snapshot = UniswapPairTotalReservesSnapshot(**{
                'token0Reserves': epoch_reserves_snapshot_map_token0,
                'token1Reserves': epoch_reserves_snapshot_map_token1,
                'token0ReservesUSD': epoch_usd_reserves_snapshot_map_token0,
                'token1ReservesUSD': epoch_usd_reserves_snapshot_map_token1,
                'chainHeightRange': EpochBase(begin=min_chain_height, end=max_chain_height),
                'timestamp': max_block_timestamp,
                'contract': data_source_contract_address
            })
            return pair_total_reserves_snapshot

    async def _prepare_epochs(
            self,
            failed_query_epochs_key,
            discarded_query_epochs_key,
            current_epoch: PowerloomCallbackProcessMessage,
            snapshot_name: str,
            failed_query_epochs_l: Optional[List]
    ):
        queued_epochs = list()
        # checks for any previously queued epochs, returns a list of such epochs in increasing order of blockheights
        if 'test' not in SETTINGS_ENV:
            failed_query_epochs = await self._redis_conn.lpop(failed_query_epochs_key)
            while failed_query_epochs:
                epoch_broadcast: PowerloomCallbackProcessMessage = PowerloomCallbackProcessMessage.parse_raw(
                    failed_query_epochs.decode('utf-8')
                )
                self._logger.info(
                    'Found queued epoch against which snapshot construction for pair contract\'s '
                    '%s failed earlier: %s',
                    snapshot_name, epoch_broadcast
                )
                queued_epochs.append(epoch_broadcast)
                # uniswap_failed_query_pair_total_reserves_epochs_redis_q_f.format(current_epoch.contract)
                failed_query_epochs = await self._redis_conn.lpop(failed_query_epochs_key)
        else:
            queued_epochs = failed_query_epochs_l if failed_query_epochs_l else list()
        queued_epochs.append(current_epoch)
        # check for continuity in epochs before ordering them
        self._logger.info(
            'Attempting to check for continuity in queued epochs to generate snapshots against pair contract\'s '
            '%s including current epoch: %s', snapshot_name, queued_epochs
        )
        continuity = True
        for idx, each_epoch in enumerate(queued_epochs):
            if idx == 0:
                continue
            if each_epoch.begin != queued_epochs[idx - 1].end + 1:
                continuity = False
                break
        if not continuity:
            # pop off current epoch added to end of this list
            queued_epochs = queued_epochs[:-1]
            self._logger.info(
                'Recording epochs as discarded during snapshot construction stage for %s: %s',
                snapshot_name, queued_epochs
            )
            for x in queued_epochs:
                await self._redis_conn.rpush(
                    discarded_query_epochs_key,
                    x.json()
                )

        return queued_epochs

    async def _construct_pair_reserves_epoch_snapshot_data(
            self,
            msg_obj: PowerloomCallbackProcessMessage,
            past_failed_epochs: Optional[List],
            enqueue_on_failure=False
    ):
        # check for enqueued failed query epochs
        epochs = await self._prepare_epochs(
            failed_query_epochs_key=uniswap_failed_query_pair_total_reserves_epochs_redis_q_f.format(msg_obj.contract),
            discarded_query_epochs_key=uniswap_discarded_query_pair_total_reserves_epochs_redis_q_f.format(msg_obj.contract),
            current_epoch=msg_obj,
            snapshot_name='pair reserves',
            failed_query_epochs_l=past_failed_epochs
        )

        results_map = await self._map_processed_epochs_to_adapters(
            epochs=epochs,
            cb_fn_async=self._fetch_token_reserves_on_chain,
            enqueue_on_failure=enqueue_on_failure,
            data_source_contract_address=msg_obj.contract,
            failed_query_redis_key=uniswap_failed_query_pair_total_reserves_epochs_redis_q_f.format(msg_obj.contract),
            transformation_lambdas=[]
        )
        return results_map

    async def _map_processed_epochs_to_adapters(
        self,
        epochs: List[PowerloomCallbackProcessMessage],
        cb_fn_async,
        enqueue_on_failure,
        data_source_contract_address,
        failed_query_redis_key,
        transformation_lambdas: List[Callable],
        **cb_kwargs
    ):
        tasks_map = dict()
        for each_epoch in epochs:
            tasks_map[(
                each_epoch.begin,
                each_epoch.end,
                each_epoch.broadcast_id
            )] = cb_fn_async(
                min_chain_height=each_epoch.begin,
                max_chain_height=each_epoch.end,
                data_source_contract_address=data_source_contract_address,
                **cb_kwargs
            )
        results = await asyncio.gather(*tasks_map.values(), return_exceptions=True)
        results_map = dict()
        for idx, each_result in enumerate(results):
            epoch_against_result = list(tasks_map.keys())[idx]
            if isinstance(each_result, Exception) and enqueue_on_failure and 'test' not in SETTINGS_ENV:
                queue_msg_obj = PowerloomCallbackProcessMessage(
                    begin=epoch_against_result[0],
                    end=epoch_against_result[1],
                    broadcast_id=epoch_against_result[2],
                    contract=data_source_contract_address
                )
                await self._redis_conn.rpush(
                    failed_query_redis_key,
                    queue_msg_obj.json()
                )
                self._logger.debug(
                    f'Enqueued epoch broadcast ID %s because reserve query failed on %s - %s | Exception: %s',
                    queue_msg_obj.broadcast_id, epoch_against_result[0], epoch_against_result[1],
                    each_result
                )
                results_map[(epoch_against_result[0], epoch_against_result[1])] = None
            else:
                for transformation in transformation_lambdas:
                    each_result = transformation(
                        each_result, data_source_contract_address, epoch_against_result[0], epoch_against_result[1]
                    )
                results_map[(
                    epoch_against_result[0], epoch_against_result[1]
                )] = each_result
        return results_map

    async def _construct_trade_volume_epoch_snapshot_data(
            self,
            msg_obj: PowerloomCallbackProcessMessage,
            past_failed_epochs: Optional[List],
            enqueue_on_failure=False
    ):
        epochs = await self._prepare_epochs(
            failed_query_epochs_key=uniswap_failed_query_pair_trade_volume_epochs_redis_q_f.format(msg_obj.contract),
            discarded_query_epochs_key=uniswap_discarded_query_pair_trade_volume_epochs_redis_q_f.format(
                msg_obj.contract),
            current_epoch=msg_obj,
            snapshot_name='trade volume and fees',
            failed_query_epochs_l=past_failed_epochs
        )

        results_map = await self._map_processed_epochs_to_adapters(
            epochs=epochs,
            cb_fn_async=get_pair_trade_volume,
            enqueue_on_failure=enqueue_on_failure,
            data_source_contract_address=msg_obj.contract,
            failed_query_redis_key=uniswap_failed_query_pair_total_reserves_epochs_redis_q_f.format(msg_obj.contract),
            transformation_lambdas=[self.transform_processed_epoch_to_trade_volume],
            rate_limit_lua_script_shas=self._rate_limiting_lua_scripts
        )
        return results_map

    def transform_processed_epoch_to_trade_volume(
            self,
            trade_vol_processed_snapshot,
            data_source_contract_address,
            epoch_begin,
            epoch_end
    ):
        self._logger.debug('Trade volume processed snapshot: %s', trade_vol_processed_snapshot)

        # Set effective trade volume at top level
        total_trades_in_usd = trade_vol_processed_snapshot['Trades']['totalTradesUSD']
        total_fee_in_usd = trade_vol_processed_snapshot['Trades']['totalFeeUSD']
        total_token0_vol = trade_vol_processed_snapshot['Trades']['token0TradeVolume']
        total_token1_vol = trade_vol_processed_snapshot['Trades']['token1TradeVolume']
        total_token0_vol_usd = trade_vol_processed_snapshot['Trades']['token0TradeVolumeUSD']
        total_token1_vol_usd = trade_vol_processed_snapshot['Trades']['token1TradeVolumeUSD']

        max_block_timestamp = trade_vol_processed_snapshot.get('timestamp')
        trade_vol_processed_snapshot.pop('timestamp', None)
        trade_volume_snapshot = UniswapTradesSnapshot(**dict(
            contract=data_source_contract_address,
            chainHeightRange=EpochBase(begin=epoch_begin, end=epoch_end),
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

    async def _update_broadcast_processing_status(self, broadcast_id, update_state):
        await self._redis_conn.hset(
            uniswap_cb_broadcast_processing_logs_zset.format(self.name),
            broadcast_id,
            json.dumps(update_state)
        )

    async def _send_audit_payload_commit_service(
            self,
            audit_stream,
            original_epoch: PowerloomCallbackProcessMessage,
            snapshot_name,
            epoch_snapshot_map: Dict[Tuple[int, int], Union[UniswapPairTotalReservesSnapshot, UniswapTradesSnapshot, None]]
    ):

        for each_epoch, epoch_snapshot in epoch_snapshot_map.items():
            if not epoch_snapshot:
                self._logger.error(
                    'No epoch snapshot to commit. Construction of snapshot failed for %s against epoch %s',
                    snapshot_name, each_epoch
                )
                # TODO: standardize/unify update log data model
                update_log = {
                    'worker': self._unique_id,
                    'update': {
                        'action': f'SnapshotBuild-{snapshot_name}',
                        'info': {
                            'original_epoch': original_epoch.dict(),
                            'cur_epoch': {'begin': each_epoch[0], 'end': each_epoch[1]},
                            'status': 'Failed'
                        }
                    }
                }

                await self._redis_conn.zadd(
                    name=uniswap_cb_broadcast_processing_logs_zset.format(original_epoch.broadcast_id),
                    mapping={json.dumps(update_log): int(time.time())}
                )
            else:
                update_log = {
                    'worker': self._unique_id,
                    'update': {
                        'action': f'SnapshotBuild-{snapshot_name}',
                        'info': {
                            'original_epoch': original_epoch.dict(),
                            'cur_epoch': {'begin': each_epoch[0], 'end': each_epoch[1]},
                            'status': 'Success',
                            'snapshot': epoch_snapshot.dict()
                        }
                    }
                }

                await self._redis_conn.zadd(
                    name=uniswap_cb_broadcast_processing_logs_zset.format(original_epoch.broadcast_id),
                    mapping={json.dumps(update_log): int(time.time())}
                )
                source_chain_details = SourceChainDetails(
                    chainID=settings.CHAIN_ID,
                    epochStartHeight=each_epoch[0],
                    epochEndHeight=each_epoch[1]
                )
                payload = epoch_snapshot.dict()
                project_id = f'uniswap_pairContract_{audit_stream}_{original_epoch.contract}_{settings.NAMESPACE}'

                commit_payload = PayloadCommitAPIRequest(
                    projectId=project_id,
                    payload=payload,
                    sourceChainDetails=source_chain_details
                )

                try:
                    r = await AuditProtocolCommandsHelper.commit_payload(
                        report_payload=commit_payload,
                        session=self._client
                    )
                except Exception as e:
                    self._logger.error('Exception committing snapshot to audit protocol: %s | dump: %s',
                                       epoch_snapshot, e, exc_info=True)
                    update_log = {
                        'worker': self._unique_id,
                        'update': {
                            'action': f'SnapshotCommit-{snapshot_name}',
                            'info': {
                                'snapshot': payload,
                                'original_epoch': original_epoch.dict(),
                                'cur_epoch': {'begin': each_epoch[0], 'end': each_epoch[1]},
                                'status': 'Failed',
                                'exception': e
                            }
                        }
                    }

                    await self._redis_conn.zadd(
                        name=uniswap_cb_broadcast_processing_logs_zset.format(original_epoch.broadcast_id),
                        mapping={json.dumps(update_log): int(time.time())}
                    )
                else:
                    self._logger.debug(
                        'Sent snapshot to audit protocol payload commit service: %s | Response: %s',
                        commit_payload, r
                    )
                    update_log = {
                        'worker': self._unique_id,
                        'update': {
                            'action': f'SnapshotCommit-{snapshot_name}',
                            'info': {
                                'snapshot': payload,
                                'original_epoch': original_epoch.dict(),
                                'cur_epoch': {'begin': each_epoch[0], 'end': each_epoch[1]},
                                'status': 'Success',
                                'response': r
                            }
                        }
                    }

                    await self._redis_conn.zadd(
                        name=uniswap_cb_broadcast_processing_logs_zset.format(original_epoch.broadcast_id),
                        mapping={json.dumps(update_log): int(time.time())}
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

        self._logger.debug('Got aiohttp session cache. Attempting to snapshot total reserves data in epoch %s...',
                           msg_obj)

        # TODO: refactor to accommodate multiple snapshots being generated from queued epochs
        pair_total_reserves_epoch_snapshot_map = await self._construct_pair_reserves_epoch_snapshot_data(
            msg_obj=msg_obj, enqueue_on_failure=True, past_failed_epochs=[]
        )

        await self._send_audit_payload_commit_service(
            audit_stream='pair_total_reserves',
            original_epoch=msg_obj,
            snapshot_name='pair token reserves',
            epoch_snapshot_map=pair_total_reserves_epoch_snapshot_map
        )
        # prepare trade volume snapshot
        trade_vol_epoch_snapshot_map = await self._construct_trade_volume_epoch_snapshot_data(
            msg_obj=msg_obj, enqueue_on_failure=True, past_failed_epochs=[]
        )

        await self._send_audit_payload_commit_service(
            audit_stream='trade_volume',
            original_epoch=msg_obj,
            snapshot_name='trade volume and fees',
            epoch_snapshot_map=trade_vol_epoch_snapshot_map
        )

        del self._running_callback_tasks[self_unique_id]

    def run(self):
        setproctitle(self.name)
        # setup_loguru_intercept()
        # TODO: initialize web3 object here
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

    async def _warm_up_cache_for_epoch_data(self, msg_obj: PowerloomCallbackProcessMessage):
        """
            Function to warm up the cache which is used across all snapshot constructors
            and/or for internal helper functions.
        """
        try:
            max_chain_height = msg_obj.end
            min_chain_height = msg_obj.begin

            await warm_up_cache_for_snapshot_constructors(
                loop=self.ev_loop,
                from_block=min_chain_height,
                to_block=max_chain_height
            )

        except Exception as exc:
            self._logger.warning(f"There was an error while warming-up cache for epoch data. error_msg: {exc}")
            pass

        return None

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

        # warm-up cache before constructing snapshots
        self.ev_loop.run_until_complete(self._warm_up_cache_for_epoch_data(msg_obj=msg_obj))

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
                routing_key=f'powerloom-backend-callback:{settings.NAMESPACE}:{settings.INSTANCE_ID}.pair_total_reserves_worker.processor',
                msg_body=pair_total_reserves_process_unit.json()
            )
            self._logger.debug(
                f'Sent out epoch to be processed by worker to calculate total reserves for pair contract: {pair_total_reserves_process_unit}')
        update_log = {
            'worker': self.name,
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

        self._logger = logger.bind(module=f'PowerLoom|Callbacks|PairTotalReservesProcessDistributor:{settings.NAMESPACE}-{settings.INSTANCE_ID}')

        self._connection_pool = redis.BlockingConnectionPool(**REDIS_CONN_CONF)
        queue_name = f'powerloom-backend-cb:{settings.NAMESPACE}:{settings.INSTANCE_ID}'
        self.ev_loop = asyncio.get_event_loop()
        self._rabbitmq_interactor: RabbitmqSelectLoopInteractor = RabbitmqSelectLoopInteractor(
            consume_queue_name=queue_name,
            consume_callback=self._distribute_callbacks,
            consumer_worker_name=f'PowerLoom|Callbacks|PairTotalReservesProcessDistributor:{settings.NAMESPACE}-{settings.INSTANCE_ID}'
        )
        # self.rabbitmq_interactor.start_publishing()
        self._logger.debug('Starting RabbitMQ consumer on queue %s', queue_name)
        self._rabbitmq_interactor.run()
