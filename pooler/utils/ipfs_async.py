import asyncio
import io
import json

from dynaconf import settings
from greenletio import async_
from IPFS_API import ipfshttpclient


class AsyncIpfsClient:
    def __init__(self, get, put, add_json, add_str, cat):
        self.get = get
        self.put = put
        self.add_json = add_json
        self.add_str = add_str
        self.cat = cat

    async def async_get(self, *args, **kwargs):
        return await async_(self.get)(*args, **kwargs)

    async def async_put(self, *args, **kwargs):
        return await async_(self.put)(*args, **kwargs)

    async def async_add_json(self, *args, **kwargs):
        return await async_(self.add_json)(*args, **kwargs)

    async def async_add_str(self, string):
        return await async_(self.add_str)(string)

    async def async_cat(self, *args, **kwargs):
        return await async_(self.cat)(*args, **kwargs)


client = ipfshttpclient.connect(settings.IPFS_URL)

async_ipfs_client = AsyncIpfsClient(
    get=client.dag.get,
    put=client.dag.put,
    add_json=client.add_json,
    add_str=client.add_str,
    cat=client.cat,
)

# Monkey patch the ipfs client
client.dag.get = async_ipfs_client.async_get
client.dag.put = async_ipfs_client.async_put
client.cat = async_ipfs_client.async_cat
client.add_json = async_ipfs_client.async_add_json
client.add_str = async_ipfs_client.async_add_str


async def test_async_funcs():
    out = await client.dag.put(io.BytesIO(json.dumps({'a': 'b'}).encode()))
    print(out)
    out = await client.dag.get(out.as_json()['Cid']['/'])
    print(out)
    cid = await client.add_str('asdasad')
    print(cid)
    out = await client.cat(cid)
    print(out)
    out = client.pin.rm(cid)
    print(out)


if __name__ == '__main__':
    tasks = asyncio.gather(
        test_async_funcs(),
    )

    asyncio.get_event_loop().run_until_complete(tasks)
