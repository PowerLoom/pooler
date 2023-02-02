from typing import List

import httpx
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential

from pooler.settings.config import projects_config
from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.models.data_models import IndexingRegistrationData
from pooler.utils.models.data_models import ProjectRegistrationRequest
from pooler.utils.models.data_models import ProjectRegistrationRequestForIndexing

registration_logger = logger.bind(
    module=f'PowerLoom|RegisterProjects:{settings.namespace}-{settings.instance_id}',
)

RETRY_COUNT = 2

# Define custom execption for retrying


class RequestException(Exception):
    pass


@retry(
    reraise=True,
    retry=retry_if_exception_type(RequestException),
    wait=wait_random_exponential(multiplier=2, max=128),
    stop=stop_after_attempt(RETRY_COUNT),
)
def register_projects(all_projects: List[str]):
    try:
        r = httpx.post(
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
    wait=wait_random_exponential(multiplier=2, max=128),
    stop=stop_after_attempt(RETRY_COUNT),
)
def register_projects_for_indexing(data: ProjectRegistrationRequestForIndexing):
    try:
        r = httpx.post(
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
    namespace = settings.namespace
    if not projects_config:
        registration_logger.error('No projects found. Exiting.')
        return

    project_names = []
    for project_config in projects_config:
        for project in project_config.projects:
            project_names.append(f'{project_config.project_type}_{project.lower()}_{namespace}')

    registration_logger.info(f'Registered {len(project_names)} pairs to register with audit protocol.')

    project_names.append(f'uniswap_V2PairsSummarySnapshot_{namespace}')
    project_names.append(f'uniswap_V2TokensSummarySnapshot_{namespace}')
    project_names.append(f'uniswap_V2DailyStatsSnapshot_{namespace}')
    register_projects(project_names)

    indexer_registration_data = []
    for project_config in projects_config:
        for project in project_config.projects:
            indexer_registration_data.append(
                IndexingRegistrationData(
                    projectID=f'{project_config.project_type}_{project.lower()}_{namespace}',
                    indexerConfig={'series': ['0']}
                    if 'reserves' in project_config.project_type else {'series': ['24h', '7d']},
                ),
            )

    data = ProjectRegistrationRequestForIndexing(
        projects=indexer_registration_data,
        namespace=settings.namespace,
    )

    register_projects_for_indexing(data)


if __name__ == '__main__':
    main()
