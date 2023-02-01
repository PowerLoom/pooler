import json

from pooler.utils.models.settings_model import Projects
from pooler.utils.models.settings_model import ProjectsConfig
from pooler.utils.models.settings_model import Settings

settings_file = open('pooler/settings/settings.json', 'r')
settings_dict = json.load(settings_file)

settings: Settings = Settings(**settings_dict)

project_config_paths = settings.project_config_paths


projects_file = open(project_config_paths.projects_path)
projects_dict = json.load(projects_file)

projects = Projects(**projects_dict).projects


projects_config_file = open(project_config_paths.projects_config_path)
projects_config_dict = json.load(projects_config_file)

projects_config = ProjectsConfig(**projects_config_dict).config
