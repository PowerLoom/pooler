import json
import os
from typing import List

import requests
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential

from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.models.data_models import IndexingRegistrationData
from pooler.utils.models.data_models import ProjectRegistrationRequest
from pooler.utils.models.data_models import ProjectRegistrationRequestForIndexing


registration_logger = logger.bind(
    module=f'PowerLoom|RegisterProjects:{settings.namespace}-{settings.instance_id}',
)

RETRY_COUNT = 5

# Define custom execption for retrying


class RequestException(Exception):
    pass


@retry(
    reraise=True,
    retry=retry_if_exception_type(RequestException),
    wait=wait_random_exponential(multiplier=2, min=4, max=128),
    stop=stop_after_attempt(RETRY_COUNT),
)
def register_projects(all_projects: List[str]):
    try:
        r = requests.post(
            url=settings.audit_protocol_engine.url + '/registerProjects',
            json=ProjectRegistrationRequest(projectIDs=all_projects).dict(),
        )
    except:
        raise RequestException

    if r.status_code == 200:
        registration_logger.info('Successfully registered projects with audit protocol.')
    else:
        registration_logger.error('Failed to register projects with audit protocol.')
        raise RequestException


@retry(
    reraise=True,
    retry=retry_if_exception_type(RequestException),
    wait=wait_random_exponential(multiplier=2, min=4, max=128),
    stop=stop_after_attempt(RETRY_COUNT),
)
def register_projects_for_indexing(data: ProjectRegistrationRequestForIndexing):
    try:
        r = requests.post(
            url=settings.audit_protocol_engine.url + '/registerProjectsForIndexing',
            json=data.dict(),
        )

    except:
        raise RequestException

    if r.status_code == 200:
        registration_logger.info('Successfully registered projects for indexing with audit protocol.')
    else:
        registration_logger.error('Failed to register projects for indexing with audit protocol.')
        raise RequestException


def main():
    if not os.path.exists('pooler/static/cached_pair_addresses.json'):
        registration_logger.error('No cached pair addresses found. Exiting.')
        return
    namespace = settings.namespace
    f = open('pooler/static/cached_pair_addresses.json', 'r')
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

    register_projects(all_projects)

    indexer_registration_data = []
    for contract in all_pairs:
        addr = contract.lower()
        indexer_registration_data.append(
            IndexingRegistrationData(
                projectID=f'uniswap_pairContract_pair_total_reserves_{addr}_{namespace}',
                indexerConfig={'series': ['0']},
            ),
        )
        indexer_registration_data.append(
            IndexingRegistrationData(
                projectID=f'uniswap_pairContract_trade_volume_{addr}_{namespace}',
                indexerConfig={'series': ['24h', '7d']},
            ),
        )

    data = ProjectRegistrationRequestForIndexing(
        projects=indexer_registration_data,
        namespace=settings.namespace,
    )

    register_projects_for_indexing(data)


if __name__ == '__main__':
    main()
