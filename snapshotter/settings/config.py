import json

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


preloader_config_path = settings.preloader_config_path
preloader_config_file = open(preloader_config_path)
preloader_config_dict = json.load(preloader_config_file)
preloader_config = PreloaderConfig(**preloader_config_dict)
preloaders = preloader_config.preloaders

# sanity check
# making sure all preloader types are unique
preloader_types = set()
for preloader in preloaders:
    preloader_types.add(preloader.task_type)

assert len(preloader_types) == len(preloaders)
