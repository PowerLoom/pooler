from redis import Redis
from redis_conn import REDIS_CONN_CONF
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
        r.delete(*r.keys('*projectID*polymarket*'))
    except:
        pass

    try:
        r.delete(*r.keys('*Cid*'))
    except:
        pass

    poly_last_snapshots = r.hgetall('auditprotocol:lastSeenSnapshots')
    poly_last_snapshots = list(map(lambda x: x.decode('utf-8'), poly_last_snapshots.keys()))
    for k in poly_last_snapshots:
        if 'polymarket' in k:
            r.hdel('auditprotocol:lastSeenSnapshots', k)

    try:
        c = r.delete(*r.keys('lastPruned*polymarket*'))
        print(c)
    except:
        pass

    try:
        r.delete(*r.keys('tradeVolume*'))
    except:
        pass

    try:
        r.delete(*r.keys('liquidityData*'))
    except:
        pass

    try:
        r.delete(*r.keys('*lastLiquidityAggregation'))
    except:
        pass

    try:
        r.delete(*r.keys('*lastTradeVolAggregation'))
    except:
        pass

    try:
        r.delete(*r.keys('*pendingLastCommitConfirmation*'))
    except:
        pass

    try:
        r.delete(*r.keys('*SetFor'))
    except:
        pass

    try:
        r.delete(*r.keys('payloadCommit:*'))
    except:
        pass

    try:
        r.delete(*r.keys('polymarket:*'))
    except:
        pass


if __name__ == '__main__':
    redis_cleanup()
