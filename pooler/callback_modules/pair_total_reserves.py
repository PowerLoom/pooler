import asyncio
import json
import time
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Union
from uuid import uuid4

from aio_pika import IncomingMessage
from httpx import AsyncClient
from httpx import AsyncHTTPTransport
from httpx import Limits
from httpx import Timeout
from pydantic import ValidationError
from setproctitle import setproctitle

from pooler.callback_modules.uniswap.core import get_pair_reserves
from pooler.callback_modules.utils import notify_on_task_failure
from pooler.settings.config import settings
from pooler.utils.callback_helpers import CallbackAsyncWorker
from pooler.utils.models.data_models import SnapshotterIssue
from pooler.utils.models.data_models import SnapshotterIssueSeverity
from pooler.utils.models.message_models import EpochBase
from pooler.utils.models.message_models import PowerloomCallbackProcessMessage
from pooler.utils.models.message_models import UniswapPairTotalReservesSnapshot
from pooler.utils.redis.rate_limiter import load_rate_limiter_scripts
from pooler.utils.redis.redis_keys import (
    cb_broadcast_processing_logs_zset,
)
from pooler.utils.redis.redis_keys import discarded_query_epochs_redis_q
from pooler.utils.redis.redis_keys import failed_query_epochs_redis_q


class PairTotalReservesProcessor(CallbackAsyncWorker):
    def __init__(self, name: str, **kwargs: dict) -> None:
        self._stream = 'uniswap_pairContract_pair_total_reserves'
        super(PairTotalReservesProcessor, self).__init__(
            name=name,
            rmq_q=f'powerloom-backend-cb-{self._stream}:{settings.namespace}:{settings.instance_id}',
            rmq_routing=f'powerloom-backend-callback:{settings.namespace}:{settings.instance_id}.{self._stream}_worker',
            **kwargs,
        )
        self._rate_limiting_lua_scripts = dict()
        self._async_transport = AsyncHTTPTransport(
            limits=Limits(
                max_connections=100,
                max_keepalive_connections=50,
                keepalive_expiry=None,
            ),
        )
        self._client = AsyncClient(
            # base_url=self._base_url,
            timeout=Timeout(timeout=5.0),
            follow_redirects=False,
            transport=self._async_transport,
        )

    async def _fetch_token_reserves_on_chain(
        self,
        min_chain_height: int,
        max_chain_height: int,
        data_source_contract_address: str,
    ) -> Optional[Dict[str, Union[int, float]]]:
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
                fetch_timestamp=True,
            )
        except Exception as exc:
            self._logger.opt(exception=True).error(
                (
                    'Pair-Reserves function failed for epoch:'
                    f' {min_chain_height}-{max_chain_height} | error_msg:{exc}'
                ),
            )
            # if querying fails, we are going to ensure it is recorded for future processing
            return None
        else:
            for block_num in range(min_chain_height, max_chain_height + 1):
                block_pair_total_reserves = pair_reserve_total.get(block_num)
                fetch_ts = True if block_num == max_chain_height else False

                epoch_reserves_snapshot_map_token0[
                    f'block{block_num}'
                ] = block_pair_total_reserves['token0']
                epoch_reserves_snapshot_map_token1[
                    f'block{block_num}'
                ] = block_pair_total_reserves['token1']
                epoch_usd_reserves_snapshot_map_token0[
                    f'block{block_num}'
                ] = block_pair_total_reserves['token0USD']
                epoch_usd_reserves_snapshot_map_token1[
                    f'block{block_num}'
                ] = block_pair_total_reserves['token1USD']

                if fetch_ts:
                    if not block_pair_total_reserves.get('timestamp', None):
                        self._logger.error(
                            (
                                'Could not fetch timestamp against max block'
                                ' height in epoch {} - {}to calculate pair'
                                ' reserves for contract {}. Using current time'
                                ' stamp for snapshot construction'
                            ),
                            data_source_contract_address,
                            min_chain_height,
                            max_chain_height,
                        )
                    else:
                        max_block_timestamp = block_pair_total_reserves.get(
                            'timestamp',
                        )
            pair_total_reserves_snapshot = UniswapPairTotalReservesSnapshot(
                **{
                    'token0Reserves': epoch_reserves_snapshot_map_token0,
                    'token1Reserves': epoch_reserves_snapshot_map_token1,
                    'token0ReservesUSD': epoch_usd_reserves_snapshot_map_token0,
                    'token1ReservesUSD': epoch_usd_reserves_snapshot_map_token1,
                    'chainHeightRange': EpochBase(
                        begin=min_chain_height, end=max_chain_height,
                    ),
                    'timestamp': max_block_timestamp,
                    'contract': data_source_contract_address,
                },
            )
            return pair_total_reserves_snapshot

    async def _prepare_epochs(
        self,
        failed_query_epochs_key: str,
        stream: str,
        discarded_query_epochs_key: str,
        current_epoch: PowerloomCallbackProcessMessage,
        snapshot_name: str,
        failed_query_epochs_l: Optional[List],
    ) -> List[PowerloomCallbackProcessMessage]:
        queued_epochs = list()
        # checks for any previously queued epochs, returns a list of such epochs in increasing order of blockheights
        if settings.env != 'test':
            project_id = (
                f'{stream}_{current_epoch.contract}_{settings.namespace}'
            )
            fall_behind_reset_threshold = (
                settings.rpc.skip_epoch_threshold_blocks
            )
            failed_query_epochs = await self._redis_conn.lpop(
                failed_query_epochs_key,
            )
            while failed_query_epochs:
                epoch_broadcast: PowerloomCallbackProcessMessage = (
                    PowerloomCallbackProcessMessage.parse_raw(
                        failed_query_epochs.decode('utf-8'),
                    )
                )
                if (
                    current_epoch.begin - epoch_broadcast.end >
                    fall_behind_reset_threshold
                ):
                    # send alert
                    await self._client.post(
                        url=settings.issue_report_url,
                        json=SnapshotterIssue(
                            instanceID=settings.instance_id,
                            severity=SnapshotterIssueSeverity.medium,
                            issueType='SKIP_QUEUED_EPOCH',
                            projectID=project_id,
                            epochs=[epoch_broadcast.end],
                            timeOfReporting=int(time.time()),
                            serviceName=f'Pooler|CallbackProcessor|{stream}',
                        ).dict(),
                    )
                    await self._redis_conn.rpush(
                        discarded_query_epochs_key,
                        epoch_broadcast.json(),
                    )
                    self._logger.warning(
                        (
                            'Project {} | QUEUED Epoch {} processing has fallen'
                            ' behind by more than {} blocks, alert sent to DAG'
                            ' Verifier | Discarding queued epoch'
                        ),
                        project_id,
                        epoch_broadcast,
                        fall_behind_reset_threshold,
                    )
                else:
                    self._logger.info(
                        (
                            'Found queued epoch against which snapshot'
                            " construction for pair contract's {} failed"
                            ' earlier: {}'
                        ),
                        snapshot_name,
                        epoch_broadcast,
                    )
                    queued_epochs.append(epoch_broadcast)
                failed_query_epochs = await self._redis_conn.lpop(
                    failed_query_epochs_key,
                )
        else:
            queued_epochs = (
                failed_query_epochs_l if failed_query_epochs_l else list()
            )
        queued_epochs.append(current_epoch)
        # check for continuity in epochs before ordering them
        self._logger.info(
            (
                'Attempting to check for continuity in queued epochs to'
                " generate snapshots against pair contract's {} including"
                ' current epoch: {}'
            ),
            snapshot_name,
            queued_epochs,
        )
        continuity = True
        for idx, each_epoch in enumerate(queued_epochs):
            if idx == 0:
                continue
            if each_epoch.begin != queued_epochs[idx - 1].end + 1:
                continuity = False
                break
        if not continuity:
            # mark others as discarded
            discarded_epochs = queued_epochs[:-1]
            # pop off current epoch added to end of this list
            queued_epochs = [queued_epochs[-1]]
            self._logger.info(
                (
                    'Recording epochs as discarded during snapshot construction'
                    ' stage for {}: {}'
                ),
                snapshot_name,
                queued_epochs,
            )
            for x in discarded_epochs:
                await self._redis_conn.rpush(
                    discarded_query_epochs_key,
                    x.json(),
                )
        return queued_epochs

    async def _construct_pair_reserves_epoch_snapshot_data(
        self,
        msg_obj: PowerloomCallbackProcessMessage,
        past_failed_epochs: Optional[List],
        enqueue_on_failure: bool = False,
    ):
        # check for enqueued failed query epochs
        epochs = await self._prepare_epochs(
            failed_query_epochs_key=failed_query_epochs_redis_q.format(
                self._stream, msg_obj.contract,
            ),
            discarded_query_epochs_key=discarded_query_epochs_redis_q.format(
                self._stream, msg_obj.contract,
            ),
            current_epoch=msg_obj,
            snapshot_name='pair reserves',
            failed_query_epochs_l=past_failed_epochs,
            stream=self._stream,
        )

        results_map = await self._map_processed_epochs_to_adapters(
            epochs=epochs,
            cb_fn_async=self._fetch_token_reserves_on_chain,
            enqueue_on_failure=enqueue_on_failure,
            data_source_contract_address=msg_obj.contract,
            failed_query_epochs_key=failed_query_epochs_redis_q.format(
                self._stream, msg_obj.contract,
            ),
            transformation_lambdas=[],
        )
        return results_map

    async def _map_processed_epochs_to_adapters(
        self,
        epochs: List[PowerloomCallbackProcessMessage],
        cb_fn_async,
        enqueue_on_failure,
        data_source_contract_address,
        failed_query_epochs_key,
        transformation_lambdas: List[Callable],
        **cb_kwargs,
    ):
        tasks_map = dict()
        for each_epoch in epochs:
            tasks_map[
                (
                    each_epoch.begin,
                    each_epoch.end,
                    each_epoch.broadcast_id,
                )
            ] = cb_fn_async(
                min_chain_height=each_epoch.begin,
                max_chain_height=each_epoch.end,
                data_source_contract_address=data_source_contract_address,
                **cb_kwargs,
            )
        results = await asyncio.gather(
            *tasks_map.values(), return_exceptions=True,
        )
        results_map = dict()
        for idx, each_result in enumerate(results):
            epoch_against_result = list(tasks_map.keys())[idx]
            if (
                isinstance(each_result, Exception) and
                enqueue_on_failure and
                settings.env != 'test'
            ):
                queue_msg_obj = PowerloomCallbackProcessMessage(
                    begin=epoch_against_result[0],
                    end=epoch_against_result[1],
                    broadcast_id=epoch_against_result[2],
                    contract=data_source_contract_address,
                )
                await self._redis_conn.rpush(
                    failed_query_epochs_key,
                    queue_msg_obj.json(),
                )
                self._logger.debug(
                    (
                        'Enqueued epoch broadcast ID {} because reserve query'
                        ' failed on {} - {} | Exception: {}'
                    ),
                    queue_msg_obj.broadcast_id,
                    epoch_against_result[0],
                    epoch_against_result[1],
                    each_result,
                )
                results_map[
                    (epoch_against_result[0], epoch_against_result[1])
                ] = None
            else:
                if not isinstance(each_result, Exception):
                    for transformation in transformation_lambdas:
                        each_result = transformation(
                            each_result,
                            data_source_contract_address,
                            epoch_against_result[0],
                            epoch_against_result[1],
                        )
                    results_map[
                        (
                            epoch_against_result[0],
                            epoch_against_result[1],
                        )
                    ] = each_result
                return results_map

    async def _update_broadcast_processing_status(
        self, broadcast_id, update_state,
    ):
        await self._redis_conn.hset(
            cb_broadcast_processing_logs_zset.format(self.name),
            broadcast_id,
            json.dumps(update_state),
        )

    @notify_on_task_failure
    async def _processor_task(self, msg_obj: PowerloomCallbackProcessMessage):
        self._logger.debug(
            'Processing total pair reserves callback: {}', msg_obj,
        )

        self_unique_id = str(uuid4())
        cur_task: asyncio.Task = asyncio.current_task(
            asyncio.get_running_loop(),
        )
        cur_task.set_name(
            f'aio_pika.consumer|PairTotalReservesProcessor|{msg_obj.contract}',
        )
        self._running_callback_tasks[self_unique_id] = cur_task

        await self.init_redis_pool()
        if not self._rate_limiting_lua_scripts:
            self._rate_limiting_lua_scripts = await load_rate_limiter_scripts(
                self._redis_conn,
            )
        self._logger.debug(
            'Got epoch to process for calculating total reserves for pair: {}',
            msg_obj,
        )
        pair_total_reserves_epoch_snapshot_map = (
            await self._construct_pair_reserves_epoch_snapshot_data(
                msg_obj=msg_obj,
                enqueue_on_failure=True,
                past_failed_epochs=[],
            )
        )

        await self._send_audit_payload_commit_service(
            audit_stream=self._stream,
            original_epoch=msg_obj,
            snapshot_name='pair token reserves',
            epoch_snapshot_map=pair_total_reserves_epoch_snapshot_map,
        )

        del self._running_callback_tasks[self_unique_id]

    async def _on_rabbitmq_message(self, message: IncomingMessage):
        await message.ack()

        try:
            msg_obj: PowerloomCallbackProcessMessage = (
                PowerloomCallbackProcessMessage.parse_raw(message.body)
            )
        except ValidationError as e:
            self._logger.opt(exception=True).error(
                (
                    'Bad message structure of callback in processor for total'
                    ' pair reserves: {}'
                ),
                e,
            )
            return
        except Exception as e:
            self._logger.opt(exception=True).error(
                (
                    'Unexpected message structure of callback in processor for'
                    ' total pair reserves: {}'
                ),
                e,
            )
            return

        asyncio.ensure_future(self._processor_task(msg_obj=msg_obj))

    def run(self):
        setproctitle(self.name)
        # setup_loguru_intercept()
        # TODO: initialize web3 object here
        # self._logger.debug('Launching epochs summation actor for total reserves of pairs...')
        super(PairTotalReservesProcessor, self).run()
