from auth.conf import auth_settings
from auth.data_models import RateLimitAuthCheck, AuthCheck, AppOwnerModel, UserStatusEnum
from fastapi import Request, Depends
from fastapi.responses import JSONResponse
from rate_limiter import generic_rate_limiter
from async_limits import parse_many
from redis import asyncio as aioredis


def inject_rate_limit_fail_response(rate_limit_auth_check_dependency: RateLimitAuthCheck) -> JSONResponse:
    if rate_limit_auth_check_dependency.authorized:
        response_body = {
            "error": {
                "details": f"Rate limit exceeded: {rate_limit_auth_check_dependency.violated_limit}. "
                           "Check response body and headers for more details on backoff.",
                "data": {
                    "rate_violated": str(rate_limit_auth_check_dependency.violated_limit),
                    "retry_after": rate_limit_auth_check_dependency.retry_after,
                    "violating_domain": rate_limit_auth_check_dependency.current_limit
                }
            }
        }
        response_headers = {'Retry-After': rate_limit_auth_check_dependency.retry_after}
        response_status = 429
    else:
        response_headers = dict()
        response_body = {
            "error": {
                "details": rate_limit_auth_check_dependency.reason
            }
        }
        if 'cache error' in rate_limit_auth_check_dependency.reason:
            response_status = 500
        else:  # usual auth issues like bad API key
            response_status = 200
    return JSONResponse(content=response_body, status_code=response_status, headers=response_headers)


async def check_user_details(
        api_key,
        app_local_cache
):
    pass


async def auth_check(
        request: Request
) -> AuthCheck:
    core_settings = request.app.state.core_settings['core_api']
    if not core_settings['auth']['enabled']:
        # public access. create owner based on IP address
        if 'CF-Connecting-IP' in request.headers:
            user_ip = request.headers['CF-Connecting-IP']
        elif 'X-Forwarded-For' in request.headers:
            proxy_data = request.headers['X-Forwarded-For']
            ip_list = proxy_data.split(',')
            user_ip = ip_list[0]  # first address in list is User IP
        else:
            user_ip = request.client.host  # For local development
        public_owner = AppOwnerModel(
            email=user_ip,
            rate_limit=core_settings['public_rate_limit'],
            active=UserStatusEnum.active  # we can plug in IP based blacklisting/whitelisting in this flag
        )
        return AuthCheck(
            authorized=True,
            owner=public_owner,
            api_key='dummy'
        )
    else:
        expected_header_key_for_auth = core_settings['auth']['header_key']
        api_key_in_header = request.headers[expected_header_key_for_auth] \
            if expected_header_key_for_auth in request.headers else None
        if not api_key_in_header:
            return AuthCheck(authorized=False, reason='no API key supplied', api_key='dummy')
        else:
            user_details = await check_user_details(
                api_key_in_header,
                request.app.state.local_user_cache
            )


async def rate_limit_auth_check(
        request: Request,
        auth_check: AuthCheck = Depends(auth_check)
) -> RateLimitAuthCheck:
    if auth_check.authorized:
        try:
            passed, retry_after, violated_limit = await generic_rate_limiter(
                parsed_limits=parse_many(auth_check.owner.rate_limit),
                key_bits=[str(request.app.state.core_settings['chain_id']), auth_check.owner.email],
                redis_conn=request.app.state.auth_aioredis_pool
            )
        except:
            auth_check.authorized = False
            auth_check.reason = 'internal cache error'
            return RateLimitAuthCheck(
                **auth_check.dict(),
                rate_limit_passed=False,
                retry_after=1,
                violated_limit='',
                current_limit=auth_check.owner.rate_limit
            )
        else:
            return RateLimitAuthCheck(
                **auth_check.dict(),
                rate_limit_passed=passed,
                retry_after=retry_after,
                violated_limit=violated_limit,
                current_limit=auth_check.owner.rate_limit
            )
    else:
        return RateLimitAuthCheck(
            **auth_check.dict(),
            rate_limit_passed=False,
            retry_after=1,
            violated_limit='',
            current_limit=''
        )
