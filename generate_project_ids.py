import hashlib

from snapshotter.settings.config import aggregator_config
from snapshotter.settings.config import projects_config
from snapshotter.settings.config import settings
from snapshotter.utils.models.settings_model import AggregateOn


def generate_base_project_id(project_type, contract):
    """
    Generate the base project ID based on the project type and contract.
    Args:
        project_type (str): The type of the project.
        contract (str): The contract associated with the project.
    Returns:
        str: The generated base project ID.
    """
    project_id = f'{project_type}:{contract.lower()}:{settings.namespace}'
    return project_id


def generate_aggregation_single_type_project_id(type_, underlying_project):
    """
    Generate the project ID for single project aggregation based on the type and underlying project.
    Args:
        type_ (str): The type of the aggregation project.
        underlying_project (str): The underlying project for aggregation.
    Returns:
        str: The generated project ID for single project aggregation.
    """
    contract = underlying_project.split(':')[-2]
    project_id = f'{type_}:{contract}:{settings.namespace}'
    return project_id


def generate_aggregation_multiple_type_project_id(type_, underlying_projects):
    """
    Generate the project ID for multiple project aggregation based on the type and underlying projects.
    Args:
        type_ (str): The type of the aggregation project.
        underlying_projects (list): The list of underlying projects for aggregation.
    Returns:
        str: The generated project ID for multiple project aggregation.
    """
    unique_project_id = ''.join(sorted(underlying_projects))
    project_hash = hashlib.sha3_256(unique_project_id.encode()).hexdigest()
    project_id = f'{type_}:{project_hash}:{settings.namespace}'
    return project_id


def generate_all_projects():
    """
    Generate all projects based on the configuration.
    Returns:
        list: The list of all generated project IDs.
    """
    base_projects = []

    for project_config in projects_config:
        project_type = project_config.project_type
        contracts = project_config.projects
        for contract in contracts:
            base_projects.append(generate_base_project_id(project_type, contract.lower()))

    aggregate_projects = []

    for config in aggregator_config:
        type_ = config.project_type

        if config.aggregate_on == AggregateOn.single_project:
            for underlying_project in base_projects:
                if config.filters.projectId not in underlying_project:
                    continue
                # Adding to base projects because other aggregates might filter based on these ids
                base_projects.append(generate_aggregation_single_type_project_id(type_, underlying_project))

        elif config.aggregate_on == AggregateOn.multi_project:
            aggregate_projects.append(generate_aggregation_multiple_type_project_id(type_, config.projects_to_wait_for))

    total_projects = base_projects + aggregate_projects
    return total_projects


def generate_projects_string(project_ids):
    """
    Generate a string representation of project IDs.
    Args:
        project_ids (list): The list of project IDs.
    Returns:
        str: The string representation of project IDs.
    """
    projects_string = '[' + ','.join('"' + project + '"' for project in project_ids) + ']'
    return projects_string


def generate_enable_string(project_ids):
    """
    Generate a string representation of project enable status.
    Args:
        project_ids (list): The list of project IDs.
    Returns:
        str: The string representation of project enable status.
    """
    enable_string = '[' + ','.join('true' for _ in project_ids) + ']'
    return enable_string


if __name__ == '__main__':
    # Generate all projects
    all_projects = generate_all_projects()

    # Print the total number of projects
    print(len(all_projects))

    # Generate and print the projects string
    projects_string = generate_projects_string(all_projects)
    print(projects_string)

    # Generate and print the enable string
    enable_string = generate_enable_string(all_projects)
    print(enable_string)