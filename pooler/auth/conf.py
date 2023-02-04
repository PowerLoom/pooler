from pooler.auth.settings.settings_models import AuthSettings

auth_settings = AuthSettings.parse_file(
    'pooler/auth/settings/auth_settings.json',
)
