from redis import Redis
from redis_conn import REDIS_CONN_CONF
from dynaconf import settings
import json


r = Redis(**REDIS_CONN_CONF)

# with open('settings.json', 'r') as f:
#     d = json.load(f)
#
# d['development']['force_seed_trade_volume'] = True
# d['development']['force_seed_liquidity'] = True
# d['development']['force_seed_outcome_prices'] = True
#
# with open('settings.json', 'w') as f:
#     json.dump(d, f)


def redis_cleanup():
    try:
        r.delete(*r.keys('*projectID*uniswap*'))
    except:
        pass

    try:
        r.delete(*r.keys('*Cid*'))
    except:
        pass

    poly_last_snapshots = r.hgetall('auditprotocol:lastSeenSnapshots')
    poly_last_snapshots = list(map(lambda x: x.decode('utf-8'), poly_last_snapshots.keys()))
    for k in poly_last_snapshots:
        if f'uniswap*{settings.NAMESPACE}*' in k:
            r.hdel('auditprotocol:lastSeenSnapshots', k)

    try:
        c = r.delete(*r.keys('lastPruned*uniswap*'))
        print(c)
    except:
        pass

    try:
        c = r.delete(*r.keys(f'*uniswap_pairContract*{settings.NAMESPACE}*slidingCache*'))
        print('Pair contract sliding cache related keys deleted: ', c)
    except:
        pass

    try:
        c = r.delete(*r.keys(f'*broadcastID*{settings.NAMESPACE}*'))
        print('Broadcast related keys deleted: ', c)
    except:
        pass

    try:
        c = r.delete(*r.keys(f'*uniswap:pairContract*{settings.NAMESPACE}*'))
        print('Other Pair contract related keys deleted: ', c)
    except:
        pass


    r.delete(f'uniswap:diffRuleSetFor:{settings.NAMESPACE}')
    try:
        r.delete(*r.keys('payloadCommit:*'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*uniswap*{settings.NAMESPACE}*pendingTransactions:*'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*uniswap*{settings.NAMESPACE}*discardedTransactions:*'))
    except:
        pass


if __name__ == '__main__':
    redis_cleanup()
