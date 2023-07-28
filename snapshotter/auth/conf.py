from snapshotter.auth.settings.settings_models import AuthSettings

auth_settings = AuthSettings.parse_file(
    'config/auth_settings.json',
)
