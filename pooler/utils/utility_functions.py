from math import floor

from pooler.utils.ipfs_async import client as ipfs_client
from pooler.utils.redis.redis_keys import uniswap_pair_hits_payload_data_key


def v2_pair_data_unpack(prop):
    prop = prop.replace('US$', '')
    prop = prop.replace(',', '')
    return int(prop)


def number_to_abbreviated_string(num):
    magnitude_dict = {
        0: '', 1: 'K', 2: 'm', 3: 'b', 4: 'T', 5: 'quad',
        6: 'quin', 7: 'sext', 8: 'sept', 9: 'o', 10: 'n', 11: 'd',
    }
    num = floor(num)
    magnitude = 0
    while num >= 1000.0:
        magnitude += 1
        num = num / 1000.0
    return(f'{floor(num*100.0)/100.0}{magnitude_dict[magnitude]}')


async def retrieve_payload_data(payload_cid, writer_redis_conn=None, logger=None):
    """
        - Given a payload_cid, get its data from ipfs, at the same time increase its hit
    """
    if writer_redis_conn:
        await writer_redis_conn.zincrby(uniswap_pair_hits_payload_data_key, 1.0, payload_cid)
        if logger:
            logger.debug('Payload Data hit for: ')
            logger.debug(payload_cid)

    """ Get the payload Data from ipfs """
    payload_data = await ipfs_client.cat(payload_cid)
    if payload_data is not None:
        payload_data = payload_data.decode('utf-8')
    return payload_data
