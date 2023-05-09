import sys
import os
current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
sys.path.append(parent)
import pooler.utils.ipfs.async_ipfshttpclient.utils.addr as addr_util
from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.ipfs.async_ipfshttpclient.dag import DAGSection
from pooler.utils.ipfs.async_ipfshttpclient.dag import IPFSAsyncClientError
from httpx import AsyncClient, Timeout, Limits, AsyncHTTPTransport
from async_ipfshttpclient.dag import DAGSection, IPFSAsyncClientError
import json
import asyncio

class AsyncIPFSClient:
    def __init__(
            self,
            addr,
            api_base='api/v0'

    ):
        self._base_url, self._host_numeric = addr_util.multiaddr_to_url_data(addr, api_base)
        self.dag = None
        self._client = None
        self._logger = logger.bind(module='IPFSAsyncClient')

    async def init_session(self):
        if not self._client:
            self._async_transport = AsyncHTTPTransport(
                limits=Limits(
                    max_connections=settings.ipfs.connection_limits.max_connections, 
                    max_keepalive_connections=settings.ipfs.connection_limits.max_connections, 
                    keepalive_expiry=settings.ipfs.connection_limits.keepalive_expiry
                )
            )
            self._client = AsyncClient(
                base_url=self._base_url,
                timeout=Timeout(settings.ipfs.timeout),
                follow_redirects=False,
                transport=self._async_transport
            )
            self.dag = DAGSection(self._client)
            self._logger.debug('Inited IPFS client on base url {}', self._base_url)

    def add_str(self, string, **kwargs):
        # TODO
        pass

    async def add_bytes(self, data: bytes, **kwargs):
        files = {'': data}
        r = await self._client.post(
            url=f'/add?cid-version=1',
            files=files
        )
        if r.status_code != 200:
            raise IPFSAsyncClientError(f"IPFS client error: add_bytes operation, response:{r}")

        try:
            return json.loads(r.text)
        except json.JSONDecodeError:
            return r.text


    async def add_json(self, json_obj, **kwargs):
        try:
            json_data = json.dumps(json_obj).encode('utf-8')
        except Exception as e:
            raise e

        cid = await self.add_bytes(json_data, **kwargs)
        return cid['Hash']

    async def cat(self, cid, **kwargs):
        response_body = ''
        last_response_code = None
        async with self._client.stream(method='POST', url=f'/cat?arg={cid}') as response:
            if response.status_code != 200:
                raise IPFSAsyncClientError(f'IPFS client error: cat on CID {cid}, response status code error: {response.status_code}')

            async for chunk in response.aiter_text():
                response_body += chunk
            last_response_code = response.status_code
        if not response_body:
            raise IPFSAsyncClientError(f'IPFS client error: cat on CID {cid}, response body empty. response status code error: {last_response_code}')
        return response_body

    async def get_json(self, cid, **kwargs):
        json_data = await self.cat(cid)
        try:
            return json.loads(json_data)
        except json.JSONDecodeError:
            return json_data


class AsyncIPFSClientSingleton:
    def __init__(self):
        self._ipfs_write_client = AsyncIPFSClient(addr=settings.ipfs.url)
        self._ipfs_read_client = AsyncIPFSClient(addr=settings.ipfs.reader_url)
        self._initialized = False

    async def init_sessions(self):
        if self._initialized:
            return
        await self._ipfs_write_client.init_session()
        await self._ipfs_read_client.init_session()
        self._initialized = True
