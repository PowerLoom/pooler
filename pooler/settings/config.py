import json

from pooler.utils.models.settings_model import Settings

f = open('pooler/settings/settings.json', 'r')
settings_dict = json.load(f)

settings: Settings = Settings(**settings_dict)
