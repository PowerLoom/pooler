from enum import Enum
from typing import List
from typing import Optional

from pydantic import BaseModel


class UserStatusEnum(str, Enum):
    active = "active"
    inactive = "inactive"


class AddApiKeyRequest(BaseModel):
    api_key: str


class AppOwnerModel(BaseModel):
    email: str
    rate_limit: str
    active: UserStatusEnum
    callsCount: int = 0
    throttledCount: int = 0
    next_reset_at: int


class UserAllDetailsResponse(AppOwnerModel):
    active_api_keys: List[str]
    revoked_api_keys: List[str]


class AuthCheck(BaseModel):
    authorized: bool = False
    api_key: str
    reason: str = ""
    owner: Optional[AppOwnerModel] = None


class RateLimitAuthCheck(AuthCheck):
    rate_limit_passed: bool = False
    retry_after: int = 1
    violated_limit: str
    current_limit: str
