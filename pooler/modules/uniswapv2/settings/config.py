import json
import os

from .settings_model import Settings

dir_path = os.path.dirname(os.path.realpath(__file__))
settings_file = open(os.path.join(dir_path, 'settings.json'), 'r')
settings_dict = json.load(settings_file)

settings: Settings = Settings(**settings_dict)
