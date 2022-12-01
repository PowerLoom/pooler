from urllib.parse import urljoin
from dynaconf import settings
import httpx
import os
import json



def main():
    if not os.path.exists('static/cached_pair_addresses.json'):
        print('No pair addresses supplied in static/cached_pair_addresses.json')
        return
    f = open('static/cached_pair_addresses.json', 'r')
    pairs = json.loads(f.read())

    if len(pairs) <= 0:
        print('No pair addresses supplied in static/cached_pair_addresses.json')
        return

    for each_pair in pairs:
        addr = each_pair.lower()
        for audit_stream in ['pair_total_reserves', 'trade_volume']:
            project_id = f'uniswap_pairContract_{audit_stream}_{addr}'
            resp = httpx.post(
                url=urljoin(settings.AUDIT_PROTOCOL_ENGINE.URL, 'registerProject'),
                json={'projectId': project_id},
                headers={'X-API-KEY': settings.NAMESPACE}
            )
            if resp.status_code in range(200, 300):
                print(f'Successfully registered project on Audit Protocol for snapshotting | contract {each_pair} '
                      f'| Stream: {audit_stream} against API key {settings.NAMESPACE} | Project ID: '
                      f'{project_id}_{settings.NAMESPACE}')


if __name__ == '__main__':
    main()
