def all_users_set():
    return 'allUsers'


def user_details_htable(email: str):
    return f'user:{email}'


def user_api_keys_set(email: str):
    return f'user:{email}:apikeys'
