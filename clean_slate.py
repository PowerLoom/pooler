from redis import Redis
from redis_conn import REDIS_CONN_CONF
from dynaconf import settings
import json
import fnmatch
import ipfshttpclient
import argparse


client = ipfshttpclient.connect(addr=settings['ipfs_url'], session=True)
# Define the parser
parser = argparse.ArgumentParser(description='clean slate script')
parser.add_argument(
    '--ipfs', action=argparse.BooleanOptionalAction, type=bool, dest='ipfs', 
    default=False, help='cleanup ipfs keys'
)
args = parser.parse_args()

# with open('settings.json', 'r') as f:
#     d = json.load(f)
#
# d['development']['force_seed_trade_volume'] = True
# d['development']['force_seed_liquidity'] = True
# d['development']['force_seed_outcome_prices'] = True
#
# with open('settings.json', 'w') as f:
#     json.dump(d, f)


def redis_cleanup_audit_protocol():
    REDIS_AUDIT_PROTOCOL_CONFIG = {
        "host": settings['redis']['host'],
        "port": settings['redis']['port'],
        "password": settings['redis']['password'],
        "db": 13 #TODO: this should be fetched from audit-protocol config
    }

    r = Redis(**REDIS_AUDIT_PROTOCOL_CONFIG)

    try:
        c = r.delete(*r.keys(f'*{settings.NAMESPACE}*Cid*'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*{settings.NAMESPACE}*lastDagCid*'))
    except:
        pass

    try:
        c = r.delete(*r.keys(f'*uniswap*pairContract*{settings.NAMESPACE}*'))
        print('Other Pair contract related keys deleted: ', c)
    except:
        pass

    try:
        c = r.delete(*r.keys(f'*{settings.NAMESPACE}*dagVerificationStatus*'))
        print('Dag chain verification keys deleted: ', c)
    except:
        pass

    try:
        c = r.delete(*r.keys(f'*uniswap*PairsSummarySnapshot*{settings.NAMESPACE}*'))
        print('Pair summary snapshots key deleted: ', c)
    except:
        pass

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

     # try:
    #     r.delete(*r.keys('pendingPayloadCommits'))
    # except:
    #     pass

    # try:
    #     r.delete(*r.keys('CidDiff*'))
    # except:
    #     pass

    try:
        c = r.delete(*r.keys('lastPruned*uniswap*'))
        print(c)
    except:
        pass


def redis_cleanup_pooler_namespace():
    r = Redis(**REDIS_CONN_CONF)

    try:
        r.delete(*r.keys(f'*projectID*{settings.NAMESPACE}*'))
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
        c = r.delete(*r.keys(f'*uniswap_pairContract*{settings.NAMESPACE}*slidingCache*'))
        print('Pair contract sliding cache related keys deleted: ', c)
    except:
        pass

    try:
        c = r.delete(*r.keys(f'*broadcastID*{settings.NAMESPACE}*'))
        print('Broadcast related keys deleted: ', c)
    except:
        pass


    r.delete(f'uniswap:diffRuleSetFor:{settings.NAMESPACE}')

    try:
        r.delete(*r.keys(f'*uniswap*{settings.NAMESPACE}*pendingTransactions:*'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*uniswap*{settings.NAMESPACE}*pendingBlocks:*'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*uniswap*{settings.NAMESPACE}*discardedTransactions:*'))
    except:
        pass

    try:
        c = r.delete(*r.keys(f'*uniswap:pairContract*{settings.NAMESPACE}*'))
        print('Other Pair contract related keys deleted: ', c)
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


def cleanup_ipfs():
    REDIS_AUDIT_PROTOCOL_CONFIG = {
        "host": settings['redis']['host'],
        "port": settings['redis']['port'],
        "password": settings['redis']['password'],
        "db": 13 #TODO: this should be fetched from audit-protocol config
    }

    r = Redis(**REDIS_AUDIT_PROTOCOL_CONFIG)

    keys = r.keys(f'*{settings.NAMESPACE}:payloadCids*')
    keys = [key.decode('utf-8') for key in keys] if keys else []

    cids = []
    for key in keys:
        res = r.zrangebyscore(
            name=key,
            min='-inf',
            max='+inf'
        )
        cids = cids + [cid.decode('utf-8') for cid in res] if res else []
    
    print(f"Total cids to be deleted: {len(cids)}")

    for cid in cids:
        try:
            res = client.pin.rm(cid)
            print(f'Unpinned {cid} result: {res}')
        except ipfshttpclient.exceptions.ErrorResponse as err:
            if str(err) == 'not pinned or pinned indirectly':
                print(f"cid already unpinned cid:{cid}")
            else:
                print(f"Unknown error: {err}")
                raise err
        
    #print('Running garbage collector: ')
    #print(client.repo.gc())
    #TODO: we need to enforce gc here but it might timeout if there are too many cids
    #      default gc is set to 1hour, any objects which are not pinned and not queried 
    #      should get gc’d in an hour.

    



if __name__ == '__main__':
    if args.ipfs:
        print("\n\n## Starting ipfs cleanup...")
        cleanup_ipfs()
    print(f"\n\n## Starting {settings.NAMESPACE} pooler cleanup...")
    redis_cleanup_pooler_namespace()
    print("\n\n## Starting audit-protocol specific cleanup...")
    redis_cleanup_audit_protocol()

    print("\n\n## Done with clean slate!!")
