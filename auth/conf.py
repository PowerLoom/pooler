from .settings_models import AuthSettings


auth_settings = AuthSettings.parse_file('./auth_settings.json')
