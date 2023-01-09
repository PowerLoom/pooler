import json
import os

import requests

from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.models.data_models import IndexingRegistrationData
from pooler.utils.models.data_models import ProjectRegistrationRequest
from pooler.utils.models.data_models import ProjectRegistrationRequestForIndexing

registration_logger = logger.bind(
    module=f'PowerLoom|RegisterProjects:{settings.namespace}-{settings.instance_id}',
)


def main():
    if not os.path.exists('static/cached_pair_addresses.json'):
        registration_logger.error('No cached pair addresses found. Exiting.')
        return
    namespace = settings.namespace
    f = open('static/cached_pair_addresses.json', 'r')
    all_pairs = json.loads(f.read())

    if len(all_pairs) <= 0:
        registration_logger.error('No cached pair addresses found. Exiting.')
        return

    registration_logger.info(f'Found {len(all_pairs)} pairs to register with audit protocol.')

    all_projects = []
    for contract in all_pairs:
        pair_reserve_template = f'uniswap_pairContract_pair_total_reserves_{contract}_{namespace}'
        pair_trade_volume_template = f'uniswap_pairContract_trade_volume_{contract}_{namespace}'
        all_projects.append(pair_reserve_template)
        all_projects.append(pair_trade_volume_template)

    all_projects.append(f'uniswap_V2PairsSummarySnapshot_{namespace}')
    all_projects.append(f'uniswap_V2TokensSummarySnapshot_{namespace}')
    all_projects.append(f'uniswap_V2DailyStatsSnapshot_{namespace}')

    r = requests.post(
        url=settings.audit_protocol_engine + 'registerProjects',
        json=ProjectRegistrationRequest(projects=all_projects).dict(),
    )

    if r.status_code == 200:
        registration_logger.info('Successfully registered projects with audit protocol.')
    else:
        registration_logger.error('Failed to register projects with audit protocol.')

    indexer_registration_data = []
    for contract in all_pairs:
        addr = contract.lower()
        indexer_registration_data.append(
            IndexingRegistrationData(
                projectID=f'uniswap_pairContract_pair_total_reserves_{addr}_{namespace}',
                indexerConfig={'series': ['24h', '7d']},
            ),
        )
        indexer_registration_data.append(
            IndexingRegistrationData(
                projectID=f'uniswap_pairContract_trade_volume_{addr}_{namespace}',
                indexerConfig={'series': ['0']},
            ),
        )

        data = ProjectRegistrationRequestForIndexing(
            projects=indexer_registration_data,
            namespace=settings.namespace,
        )

        r = requests.post(
            url=settings.audit_protocol_engine + 'registerProjectsForIndexing',
            json=data.dict(),
        )

        if r.status_code == 200:
            registration_logger.info('Successfully registered projects for indexing with audit protocol.')
        else:
            registration_logger.error('Failed to register projects for indexing with audit protocol.')


if __name__ == '__main__':
    main()
