import json
from typing import Union

from httpx import _exceptions as httpx_exceptions
from ipfs_client.main import AsyncIPFSClient
from tenacity import retry
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential

from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.file_utils import read_text_file
from pooler.utils.ipfs.dag_utils import get_dag_block
from pooler.utils.models.data_models import BlockRetrievalFlags
from pooler.utils.models.data_models import RetrievedDAGBlock
from pooler.utils.models.data_models import RetrievedDAGBlockPayload


@retry(
    reraise=True,
    wait=wait_random_exponential(multiplier=1, max=30),
    stop=stop_after_attempt(3),
)
async def retrieve_block_data(
        project_id: str,  # only required for ease of local filesystem caching
        block_dag_cid: str,
        ipfs_read_client: AsyncIPFSClient,
        data_flag: BlockRetrievalFlags = BlockRetrievalFlags.only_dag_block,
) -> Union[RetrievedDAGBlock, RetrievedDAGBlockPayload]:
    """
        Get dag block from ipfs
        Args:
            block_dag_cid:str - The cid of the dag block that needs to be retrieved
            data_flag:int - Refer enum data model `pooler.utils.data_models.BlockRetrievalFlags`
    """
    block = await get_dag_block(block_dag_cid, project_id, ipfs_read_client=ipfs_read_client)
    # handle case of no dag_block or null payload in dag_block
    if not block:
        if data_flag == BlockRetrievalFlags.only_dag_block or data_flag == BlockRetrievalFlags.dag_block_and_payload_data:
            return RetrievedDAGBlock()
        else:
            return RetrievedDAGBlockPayload()
    logger.trace('Retrieved dag block with CID %s: %s', block_dag_cid, block)
    # the data field may not be present in the dag block because of the DAG finalizer omitting null fields in DAG block model while converting to JSON
    if 'data' not in block.keys() or block['data'] is None:
        if data_flag == BlockRetrievalFlags.dag_block_and_payload_data:
            block['data'] = RetrievedDAGBlockPayload()
            return RetrievedDAGBlock.parse_obj(block)
        elif data_flag == BlockRetrievalFlags.only_dag_block:
            return RetrievedDAGBlock.parse_obj(block)
        else:
            return RetrievedDAGBlockPayload()
    if data_flag == BlockRetrievalFlags.only_dag_block:
        return RetrievedDAGBlock.parse_obj(block)
    else:
        payload = dict()
        payload_data = await retrieve_payload_data(
            payload_cid=block['data']['cid']['/'],
            project_id=project_id,
            ipfs_read_client=ipfs_read_client,
        )
        if payload_data:
            try:
                payload_data = json.loads(payload_data)
            except json.JSONDecodeError:
                logger.error(
                    'Failed to JSON decode payload data for CID %s, project %s: %s',
                    block['data']['cid']['/'], project_id, payload_data,
                )
                payload_data = None
        payload['payload'] = payload_data
        payload['cid'] = block['data']['cid']['/']

        if data_flag == BlockRetrievalFlags.dag_block_and_payload_data:
            block['data'] = RetrievedDAGBlockPayload.parse_obj(payload)
            return RetrievedDAGBlock.parse_obj(block)

        if data_flag == BlockRetrievalFlags.only_payload_data:
            return RetrievedDAGBlockPayload.parse_obj(payload)


async def retrieve_payload_data(
        payload_cid,
        ipfs_read_client: AsyncIPFSClient,
        project_id,
):
    """
        - Given a payload_cid, get its data from ipfs, at the same time increase its hit
    """
    #payload_key = redis_keys.get_hits_payload_data_key()
    # if writer_redis_conn:
    # r = await writer_redis_conn.zincrby(payload_key, 1.0, payload_cid)
    #retrieval_utils_logger.debug("Payload Data hit for: ")
    # retrieval_utils_logger.debug(payload_cid)
    payload_data = None
    if project_id is not None:
        payload_data = read_text_file(settings.ipfs.local_cache_path + '/' + project_id + '/' + payload_cid + '.json')
    if payload_data is None:
        logger.trace('Failed to read payload with CID %s for project %s from local cache ', payload_cid, project_id)
        # Get the payload Data from ipfs
        try:
            _payload_data = await ipfs_read_client.cat(payload_cid)
        except (httpx_exceptions.TransportError, httpx_exceptions.StreamError) as e:
            logger.error('Failed to read payload with CID %s for project %s from IPFS : %s', payload_cid, project_id, e)
            return None
        else:
            # retrieval_utils_logger.info("Successfully read payload with CID %s for project %s from IPFS: %s ",
            # payload_cid,project_id, _payload_data)
            if not isinstance(_payload_data, str):
                return _payload_data.decode('utf-8')
            else:
                return _payload_data
    else:
        return payload_data


async def get_dag_chain(project_id: str, from_dag_cid: str, to_dag_cid: str, ipfs_read_client: AsyncIPFSClient):
    chain = list()
    cur_block: RetrievedDAGBlock = await retrieve_block_data(
        project_id,
        from_dag_cid,
        ipfs_read_client,
        BlockRetrievalFlags.dag_block_and_payload_data,
    )
    cur_block_cid = from_dag_cid
    chain.append(cur_block)
    while True:
        prev_dag_cid = cur_block.prevCid['/'] if cur_block.prevCid else None
        if not prev_dag_cid:
            if 'prevRoot' in cur_block and cur_block.prevRoot is not None:
                prev_dag_cid = cur_block.prevRoot
        if prev_dag_cid:
            logger.trace(
                'Attempting to fetch prev DAG block at CID: {} | Current DAG block CID: {} height: {} ',
                prev_dag_cid, cur_block_cid, cur_block.height,
            )
            prev_dag_block: RetrievedDAGBlock = await retrieve_block_data(
                project_id,
                cur_block.prevCid['/'],
                ipfs_read_client,
                BlockRetrievalFlags.dag_block_and_payload_data,
            )
            logger.trace(
                'Fetched prev DAG block at CID: {} height: {} | Current DAG block CID: {} height: {} | Payload: {}',
                prev_dag_cid, prev_dag_block.height, cur_block_cid, cur_block.height, prev_dag_block.data.payload,
            )
            chain.append(prev_dag_block)
            if prev_dag_cid == to_dag_cid:
                break
        else:
            break
    return chain
