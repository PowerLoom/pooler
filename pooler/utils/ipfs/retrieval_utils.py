import asyncio
import json
from typing import Union

import async_timeout
from tenacity import AsyncRetrying
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential

from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.file_utils import read_text_file
from pooler.utils.ipfs.async_ipfshttpclient.main import AsyncIPFSClient
from pooler.utils.ipfs.dag_utils import get_dag_block
from pooler.utils.models.data_models import BlockRetrievalFlags
from pooler.utils.models.data_models import RetrievedDAGBlock
from pooler.utils.models.data_models import RetrievedDAGBlockPayload
# from data_models import ProjectBlockHeightStatus, PendingTransaction


async def retrieve_block_data(
        project_id: str,  # only required for ease of local filesystem caching
        block_dag_cid: str,
        ipfs_read_client: AsyncIPFSClient,
        data_flag=BlockRetrievalFlags.only_dag_block,
) -> Union[RetrievedDAGBlock, RetrievedDAGBlockPayload]:
    """
        Get dag block from ipfs
        Args:
            block_dag_cid:str - The cid of the dag block that needs to be retrieved
            data_flag:int - Refer enum data model `utils.data_models.BlockRetrievalFlags`
    """
    async for attempt in AsyncRetrying(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_random_exponential(multiplier=1, max=30),
    ):
        with attempt:
            block = await get_dag_block(block_dag_cid, project_id, ipfs_read_client=ipfs_read_client)
            if not block:
                logger.trace(
                    'DAG block fetch was empty against CID: {} | Attempt: {}',
                    block_dag_cid, attempt.retry_state.attempt_number,
                )
                raise Exception(f'DAG block fetch was empty against CID: {block_dag_cid}')
    payload = dict()
    # adapt to simpler data model for retrieved data block
    if block:
        payload['payload'] = dict()
        payload['cid'] = block['data']['cid']['/']
        block['data'] = payload
    if data_flag == BlockRetrievalFlags.only_dag_block:
        return RetrievedDAGBlock.parse_obj(block)
    """ Get the payload Data """
    # handle case of no dag_block or null payload in dag_block
    if block['data']['cid'] != '':
        payload_data = await get_payload(
            payload_cid=block['data']['cid'],
            project_id=project_id,
            ipfs_read_client=ipfs_read_client,
        )
    else:
        payload_data = None
    if data_flag == BlockRetrievalFlags.dag_block_and_payload_data:
        block['data']['payload'] = payload_data
        return RetrievedDAGBlock.parse_obj(block)

    if data_flag == BlockRetrievalFlags.only_payload_data:
        payload['payload'] = payload_data
        return RetrievedDAGBlockPayload.parse_obj(payload)


async def get_payload(payload_cid: str, project_id: str, ipfs_read_client: AsyncIPFSClient):
    """ Given the payload cid, retrieve the payload."""
    e_obj = None
    payload = read_text_file(f'{settings.ipfs.local_cache_path}/project_id/{payload_cid}.json')
    if payload is None:
        logger.trace('Failed to read snapshot payload CID {} for project {} from local cache ', payload_cid, project_id)
        try:
            async with async_timeout.timeout(settings.ipfs.timeout) as cm:
                try:
                    payload = await ipfs_read_client.cat(payload_cid)
                    payload = json.loads(payload)
                except Exception as ex:
                    e_obj = ex
        except (asyncio.exceptions.CancelledError, asyncio.exceptions.TimeoutError) as err:
            e_obj = err
        if e_obj or cm.expired:
            return dict()
    else:
        payload = json.loads(payload)
    return payload


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
