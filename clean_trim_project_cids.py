from redis import Redis
from redis_conn import REDIS_CONN_CONF
from dynaconf import settings
import json

r = Redis(**REDIS_CONN_CONF)

def closestNumber(n, m):
    # Find the quotient
    q = int(n / m)

    # 1st possible closest number
    n1 = m * q

    # 2nd possible closest number
    if ((n * m) > 0):
        n2 = (m * (q + 1))
    else:
        n2 = (m * (q - 1))

    # if true, then n1 is the required closest number
    if (abs(n - n1) < abs(n - n2)):
        return n1

    # else n2 is the required closest number
    return n2


# intended to be a stop gap arrangement until pruning service is cleaned up and brought up to standards

# for k in r.scan_iter(match=f"projectID*uniswap*payloadCids", count=1000):
for k in r.scan_iter(match=f"projectID*uniswap*{settings.NAMESPACE}*payloadCids", count=1000):
    # print(k)
    h = r.zcard(k)
    if h > 500:
        max_del_height = closestNumber(h, 500)
        print({k.decode('utf-8'): [h, max_del_height]})
        if max_del_height > h:
            max_del_height = h - 500
        payload_cids = r.zremrangebyscore(
            name=k,
            min='-inf',
            max=max_del_height
        )
        print(f'Removed {payload_cids} CIDs against project {k}')
#
#
# for k in r.scan_iter(match=f"projectID*{settings.NAMESPACE}*Cids", count=1000):
#     if r.zcard(k) > 500:
#         count = r.zremrangebyscore(
#             name=k,
#             min=501,
#             max='-inf'
#         )
#         print(f'Removed {count} dag block CIDs against project {k}')
#
#
