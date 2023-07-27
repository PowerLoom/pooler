import io
import json
from typing import Optional

from httpx import AsyncClient
from ipfs_client.main import AsyncIPFSClient

from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import logger
from snapshotter.utils.file_utils import read_text_file
from snapshotter.utils.file_utils import write_bytes_to_file


async def send_commit_callback(httpx_session: AsyncClient, url, payload):
    if type(url) is bytes:
        url = url.decode('utf-8')
    resp = await httpx_session.post(url=url, json=payload)
    json_response = resp.json()
    return json_response


async def get_dag_block(dag_cid: str, project_id: str, ipfs_read_client: AsyncIPFSClient) -> Optional[dict]:
    dag_ipfs_fetch = False
    dag = read_text_file(settings.ipfs.local_cache_path + '/' + project_id + '/' + dag_cid + '.json')
    try:
        dag_json = json.loads(dag)
    except:
        dag_ipfs_fetch = True
    else:
        return dag_json
    if dag_ipfs_fetch:
        dag = await ipfs_read_client.dag.get(dag_cid)
        # TODO: should be aiofiles
        write_bytes_to_file(
            settings.ipfs.local_cache_path + '/' + project_id,
            '/' + dag_cid + '.json', str(dag).encode('utf-8'),
        )
        return dag.as_json()


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
