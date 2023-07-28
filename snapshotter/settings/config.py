import json

from snapshotter.utils.models.settings_model import AggregatorConfig
from snapshotter.utils.models.settings_model import PreloaderConfig
from snapshotter.utils.models.settings_model import ProjectsConfig
from snapshotter.utils.models.settings_model import Settings

settings_file = open('config/settings.json', 'r')
settings_dict = json.load(settings_file)

settings: Settings = Settings(**settings_dict)

projects_config_path = settings.projects_config_path
projects_config_file = open(projects_config_path)
projects_config_dict = json.load(projects_config_file)
projects_config = ProjectsConfig(**projects_config_dict).config

# sanity check
# making sure all project types are unique
project_types = set()
for project in projects_config:
    project_types.add(project.project_type)
assert len(project_types) == len(projects_config)

aggregator_config_path = settings.aggregator_config_path
aggregator_config_file = open(aggregator_config_path)
aggregator_config_dict = json.load(aggregator_config_file)
aggregator_config = AggregatorConfig(**aggregator_config_dict).config

# sanity check
# making sure all aggregator types are unique
aggregator_types = set()
for aggregator in aggregator_config:
    aggregator_types.add(aggregator.project_type)
assert len(aggregator_types) == len(aggregator_config)

assert len(project_types & aggregator_types) == 0


preloader_config_path = settings.preloader_config_path
preloader_config_file = open(preloader_config_path)
preloader_config_dict = json.load(preloader_config_file)
preloader_config = PreloaderConfig(**preloader_config_dict)
preloaders = preloader_config.preloaders
delegate_tasks = preloader_config.delegate_tasks

# sanity check
# making sure all preloader types are unique
preloader_types = set()
for preloader in preloaders:
    preloader_types.add(preloader.task_type)

assert len(preloader_types) == len(preloaders)

delegate_task_types = set()
for delegate_task in delegate_tasks:
    delegate_task_types.add(delegate_task.task_type)

assert len(delegate_task_types) == len(delegate_tasks)

assert len(preloader_types & delegate_task_types) == 0
