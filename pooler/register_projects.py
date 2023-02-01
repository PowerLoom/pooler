from typing import List

import httpx
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_random_exponential

from pooler.settings.config import projects
from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.models.data_models import ProjectRegistrationRequest


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


def main():
    namespace = settings.namespace
    all_projects = [project for project in projects if project.enabled]

    if len(all_projects) <= 0:
        registration_logger.error('No projects found. Exiting.')
        return

    registration_logger.info(f'Found {len(all_projects)} pairs to register with audit protocol.')

    project_names = []
    for project in all_projects:
        project_names.append(f'{project.contract}_{project.action}_{namespace}')

    register_projects(project_names)


if __name__ == '__main__':
    main()
