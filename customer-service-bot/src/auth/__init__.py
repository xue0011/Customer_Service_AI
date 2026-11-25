"""认证授权：密码哈希、JWT、RBAC、FastAPI 依赖、用户服务。"""

from .deps import get_current_user, get_current_user_optional
from .jwt import create_access_token, create_refresh_token, decode_token
from .passwords import hash_password, verify_password
from .rbac import PERMISSIONS, can, require_permission, require_role
from .service import (
    authenticate,
    ensure_super_user,
    issue_tokens,
    refresh_access,
    register_or_get_customer,
)

__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "PERMISSIONS",
    "can",
    "require_role",
    "require_permission",
    "get_current_user",
    "get_current_user_optional",
    "authenticate",
    "issue_tokens",
    "refresh_access",
    "ensure_super_user",
    "register_or_get_customer",
]
