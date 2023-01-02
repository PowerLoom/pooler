def all_users_set():
    return 'allUsers'


def user_details_htable(email: str):
    return f'user:{email}'


def user_active_api_keys_set(email: str):
    return f'user:{email}:apikeys'


def user_revoked_api_keys_set(email: str):
    return f'user:{email}:revokedApikeys'


def api_key_to_owner_key(api_key: str):
    return f'apikey:{api_key}:owner'
