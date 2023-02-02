import json

from pooler.utils.models.settings_model import ProjectsConfig
from pooler.utils.models.settings_model import Settings

settings_file = open('pooler/settings/settings.json', 'r')
settings_dict = json.load(settings_file)

settings: Settings = Settings(**settings_dict)

projects_config_path = settings.projects_config_path
projects_config_file = open(projects_config_path)
projects_config_dict = json.load(projects_config_file)
projects_config = ProjectsConfig(**projects_config_dict).config

enabled_projects = []

for project_config in projects_config:
    enabled_projects.extend(project_config.projects)
