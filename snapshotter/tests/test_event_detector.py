from snapshotter.system_event_detector import EventDetectorProcess
from snapshotter.utils.rpc import RpcHelper


async def test_event_detector():
    # ed = EventDetectorProcess(name='ed')

    # events = await ed.get_events(
    #     from_block=19057638,
    #     to_block=19057738,

    # )
    rpc_helper = RpcHelper()
    events = await rpc_helper.get_events_logs(
        from_block=19057638,
        to_block=19057738,
        contract_address='0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640',
    )
    print(events)

if __name__ == '__main__':
    import asyncio
    asyncio.run(test_event_detector())
