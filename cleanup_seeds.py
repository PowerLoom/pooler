from redis import Redis
from redis_conn import REDIS_CONN_CONF
from dynaconf import settings

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
        r.delete(*r.keys(f'*{settings.NAMESPACE}*consolidated*'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*{settings.NAMESPACE}*queued*Epoch*'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*{settings.NAMESPACE}*Lock'))
    except:
        pass

    try:
        r.delete(*r.keys(f'*{settings.NAMESPACE}*Base'))
    except:
        pass


if __name__ == '__main__':
    redis_cleanup()
