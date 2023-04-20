import asyncio
import uuid

import httpx

from ..trade_volume import (
    TradeVolumeProcessor,
)
from pooler.init_rabbitmq import init_exchanges_queues
from pooler.settings.config import settings
from pooler.utils.models.message_models import PowerloomSnapshotProcessMessage


async def test_construction_snapshot(
    epoch_begin,
    epoch_end,
    pair_contract,
    failed_queued_epochs_past=2,
):
    cur_epoch = PowerloomSnapshotProcessMessage(
        begin=epoch_begin,
        end=epoch_end,
        broadcastId=str(uuid.uuid4()),
        contract=pair_contract,
    )

    failed_query_epochs = list()
    for _ in range(failed_queued_epochs_past):
        past_failed_query_epoch_end = epoch_begin - 1
        past_failed_query_epoch_begin = (
            past_failed_query_epoch_end - settings.epoch.height + 1
        )
        failed_query_epochs.insert(
            0,
            PowerloomSnapshotProcessMessage(
                begin=past_failed_query_epoch_begin,
                end=past_failed_query_epoch_end,
                broadcastId=str(uuid.uuid4()),
                contract=pair_contract,
            ),
        )
        epoch_begin = past_failed_query_epoch_begin
    print(failed_query_epochs)

    p = TradeVolumeProcessor(name='testDummyProcessor')
    r = await p._construct_trade_volume_epoch_snapshot_data(
        cur_epoch,
        past_failed_epochs=failed_query_epochs,
    )
    print(r)


if __name__ == '__main__':
    pair_contract = '0xae461ca67b15dc8dc81ce7615e0320da1a9ab8d5'
    init_exchanges_queues()
    consensus_epoch_tracker_url = (
        f'{settings.consensus.url}{settings.consensus.epoch_tracker_path}'
    )
    response = httpx.get(url=consensus_epoch_tracker_url)
    if response.status_code != 200:
        raise Exception(
            f'Error while fetching current epoch data: {response.status_code}',
        )
    current_epoch = response.json()
    asyncio.run(
        test_construction_snapshot(
            epoch_end=current_epoch['epochStartBlockHeight'],
            epoch_begin=current_epoch['epochEndBlockHeight'],
            pair_contract=pair_contract,
            failed_queued_epochs_past=2,
        ),
    )
