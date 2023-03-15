import asyncio
import io
import json

import async_timeout
from httpx import AsyncClient

from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.file_utils import read_text_file
from pooler.utils.file_utils import write_bytes_to_file
from pooler.utils.ipfs.async_ipfshttpclient.main import AsyncIPFSClient


class IPFSDAGCreationException(Exception):
    pass


async def send_commit_callback(httpx_session: AsyncClient, url, payload):
    if type(url) is bytes:
        url = url.decode('utf-8')
    resp = await httpx_session.post(url=url, json=payload)
    json_response = resp.json()
    return json_response


async def get_dag_block(dag_cid: str, project_id: str, ipfs_read_client: AsyncIPFSClient):
    e_obj = None
    dag = read_text_file(f'{settings.ipfs.local_cache_path}/project_id/{dag_cid}.json')
    if dag is None:
        logger.trace('Failed to read dag-block with CID {} for project {} from local cache ', dag_cid, project_id)
        try:
            async with async_timeout.timeout(settings.ipfs.timeout) as cm:
                try:
                    dag = await ipfs_read_client.dag.get(dag_cid)
                    dag = dag.as_json()
                except Exception as ex:
                    e_obj = ex
        except (asyncio.exceptions.CancelledError, asyncio.exceptions.TimeoutError) as err:
            e_obj = err
        if e_obj or cm.expired:
            return dict()
    else:
        dag = json.loads(dag)
    return dag


async def put_dag_block(dag_json: str, project_id: str, ipfs_write_client: AsyncIPFSClient):
    dag_json = dag_json.encode('utf-8')
    out = await ipfs_write_client.dag.put(io.BytesIO(dag_json), pin=True)
    dag_cid = out['Cid']['/']
    try:
        write_bytes_to_file(f'{settings.ipfs.local_cache_path}/project_id', f'/{dag_cid}.json', dag_json)
    except Exception as exc:
        logger.opt(exception=True).error(
            'Failed to write dag-block {} for project {} to local cache due to exception {}',
            dag_json, project_id, exc,
        )
    return dag_cid
