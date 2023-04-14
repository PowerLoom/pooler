import asyncio
import pprint
from pooler.settings.config import settings
from pooler.utils.indexing_worker import IndexingAsyncWorker
from pooler.utils.models.data_models import CachedDAGTailMarker, CachedIndexMarker
from pooler.utils.default_logger import logger


async def test_new_tail_seek():
    index_builder = IndexingAsyncWorker(name='test_indexing_worker')
    await index_builder.init()
    # seek tail for the first time when no prior indexes were found
    t = await index_builder._seek_tail(
        project_id='foo',
        head_dag_cid='bafyreif7kwmfpkgl64f56xqmvjzacqgkk2mtitzapqa4urqxvdxv3ltmja',  # at height 5156
        time_range=200
    )
    logger.debug('Finalized tail block index' )
    pprint.pprint(t.dict(), indent=4, width=20)
    # seek tail for the second time when prior indexes were found
    cached_index = CachedIndexMarker(
        dagTail=CachedDAGTailMarker(
            height=t.dagBlockTail.height,
            cid=t.dagBlockTailCid,
            sourceChainBlockNum=t.sourceChainBlockNum
        ),
        dagHeadCid='bafyreif7kwmfpkgl64f56xqmvjzacqgkk2mtitzapqa4urqxvdxv3ltmja'
    )
    new_tail = await index_builder._adjust_tail(
        project_id='foo',
        head_dag_cid='bafyreig4rd7nma32lvf3uvhzjxiklr7wpurstbzvvy63z4rdyqaqs4kno4',  # new index build request against head height at 5157
        head_dag_height=5157,
        time_range=200,
        last_recorded_tail_source_chain_marker=cached_index,
    )
    # logger.debug('new tail block index' )
    # pprint.pprint(new_tail.dict(), indent=4, width=20)



async def test_tail_adjustment():
    index_builder = IndexingAsyncWorker(name='test_indexing_worker')
    # set up last known state of index building
    # test the adjustment of tail accordingly
    await index_builder.init()


if __name__ == '__main__':
    try:
        asyncio.get_event_loop().run_until_complete(test_new_tail_seek())
    except Exception as e:
        logger.opt(exception=True).error('Exception: {}', e)
        asyncio.get_event_loop().stop()
