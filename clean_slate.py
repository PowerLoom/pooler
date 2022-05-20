from redis import Redis
from redis_conn import REDIS_CONN_CONF
from dynaconf import settings
import json
import fnmatch


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
        r.delete(*r.keys(f'*projectID*{settings.NAMESPACE}*'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*{settings.NAMESPACE}*Cid*'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*{settings.NAMESPACE}*lastDagCid*'))
    except:
        pass

    last_snapshots = r.hgetall('auditprotocol:lastSeenSnapshots')
    last_snapshots = list(map(lambda x: x.decode('utf-8'), last_snapshots.keys()))
    for k in last_snapshots:
        if fnmatch.fnmatch(k,f'uniswap*{settings.NAMESPACE}*'):
            r.hdel('auditprotocol:lastSeenSnapshots', k)

    try:
        r.delete(*r.keys(f'*uniswap:V2PairsSummarySnapshot*{settings.NAMESPACE}*snapshotsZset*'))
    except:
        pass

    try:
        c = r.delete(*r.keys(f'*{settings.NAMESPACE}*dagVerificationStatus*'))
        print('Dag chain verification keys deleted: ', c)
    except:
        pass

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
    # try:
    #     r.delete(*r.keys('payloadCommit:*'))
    # except:
    #     pass

    # try:
    #     r.delete(*r.keys('eventData:*'))
    # except:
    #     pass

    # try:
    #     r.delete(*r.keys('txHash*inputData'))
    # except:
    #     pass

    try:
        r.delete(*r.keys(f'*uniswap*{settings.NAMESPACE}*pendingTransactions:*'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*uniswap*{settings.NAMESPACE}*pendingBlocks:*'))
    except:
        pass

    # try:
    #     r.delete(*r.keys('pendingPayloadCommits'))
    # except:
    #     pass

    # try:
    #     r.delete(*r.keys('CidDiff*'))
    # except:
    #     pass

    try:
        r.delete(*r.keys(f'*uniswap*{settings.NAMESPACE}*discardedTransactions:*'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*uniswap*{settings.NAMESPACE}*priceHistory*'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*uniswap*{settings.NAMESPACE}*cachedData*'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*uniswap*{settings.NAMESPACE}*slidingWindowData*'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*uniswap*{settings.NAMESPACE}*cachedPairBlockHeightTokenPrice*'))
    except:
        pass


if __name__ == '__main__':
    redis_cleanup()
