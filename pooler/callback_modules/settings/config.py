
import json

from pooler.callback_modules.settings.settings_model import Settings

settings_file = open('pooler/callback_modules/settings/settings.json', 'r')
settings_dict = json.load(settings_file)

settings: Settings = Settings(**settings_dict)
