import asyncio
import uuid

from dynaconf import settings

from pooler.callback_modules.pair_total_reserves import \
    PairTotalReservesProcessor
from pooler.init_rabbitmq import init_exchanges_queues
from pooler.utils.models.message_models import PowerloomCallbackProcessMessage


async def test_construction_snapshot(
        epoch_begin,
        epoch_end,
        pair_contract,
        failed_queued_epochs_past=2,
):
    cur_epoch = PowerloomCallbackProcessMessage(
        begin=epoch_begin,
        end=epoch_end,
        broadcast_id=str(uuid.uuid4()),
        contract=pair_contract,
    )

    failed_query_epochs = list()
    for _ in range(failed_queued_epochs_past):
        past_failed_query_epoch_end = epoch_begin - 1
        past_failed_query_epoch_begin = past_failed_query_epoch_end - settings.EPOCH.HEIGHT + 1
        failed_query_epochs.insert(
            0,
            PowerloomCallbackProcessMessage(
                begin=past_failed_query_epoch_begin,
                end=past_failed_query_epoch_end,
                broadcast_id=str(uuid.uuid4()),
                contract=pair_contract,
            ),
        )
        epoch_begin = past_failed_query_epoch_begin
    print(failed_query_epochs)

    p = PairTotalReservesProcessor(name='testDummyProcessor')
    r = await p._construct_trade_volume_epoch_snapshot_data(
        cur_epoch,
        past_failed_epochs=failed_query_epochs,
    )
    print(r)

if __name__ == '__main__':
    pair_contract = '0xe1573b9d29e2183b1af0e743dc2754979a40d237'
    init_exchanges_queues()
    asyncio.run(
        test_construction_snapshot(
            epoch_end=15798619,
            epoch_begin=15798610,
            pair_contract=pair_contract,
        ),
    )
    # p.run()
    # p.join(timeout=1)

    # asyncio.run(test_construction_snapshot(
    #         21,
    #         30,
    #         pair_contract
    #     )
    # )
