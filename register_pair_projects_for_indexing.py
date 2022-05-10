from dynaconf import settings
from redis_conn import provide_redis_conn_insta
import os
import json
import redis


@provide_redis_conn_insta
def main(redis_conn: redis.Redis=None):
    if not os.path.exists('static/cached_pair_addresses.json'):
        return
    f = open('static/cached_pair_addresses.json', 'r')
    pairs = json.loads(f.read())

    if len(pairs) <= 0:
        return
    streams = ['pair_total_reserves', 'trade_volume']
    project_ids = dict()
    for each_pair in pairs:
        addr = each_pair.lower()
        for stream in streams:
            project_ids.update({f'uniswap_pairContract_{stream}_{addr}_{settings.NAMESPACE}': json.dumps({'series': ['24h', '7d']})})
    redis_conn.hset('cache:indexesRequested', mapping=project_ids)


if __name__ == '__main__':
    main()
