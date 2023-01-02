from auth.settings_models import AuthSettings

auth_settings = AuthSettings.parse_file('auth/auth_settings.json')
