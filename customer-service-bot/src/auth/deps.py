"""FastAPI 鉴权依赖：解析 Bearer JWT → 加载 User → 注入 Actor 上下文。"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..database.db import get_session_factory
from ..database.models import User
from ..database.repositories_async import UserRepository
from ..infra.context import Actor, set_actor
from .jwt import decode_token

_security = HTTPBearer(auto_error=False)


async def _load_user(user_id: str) -> User | None:
    if not user_id:
        return None
    factory = get_session_factory()
    async with factory() as s:
        repo = UserRepository(s)
        return await repo.get_by_id(user_id)


def _actor_from(user: User) -> Actor:
    return Actor(
        user_id=user.id,
        role=user.role,
        customer_id=user.customer_id,
        display_name=user.display_name,
        is_authenticated=True,
    )


async def get_current_user(
    cred: HTTPAuthorizationCredentials = Depends(_security),
) -> User:
    """强制鉴权：缺失/无效 → 401。成功后注入 Actor 上下文。"""
    if cred is None or not cred.credentials:
        raise HTTPException(status_code=401, detail="未认证：请提供 Bearer 令牌。")
    try:
        payload = decode_token(cred.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="令牌无效或已过期。") from None
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="令牌类型错误，请使用 access token。")
    user = await _load_user(payload.get("sub", ""))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用。")
    set_actor(_actor_from(user))
    return user


async def get_current_user_optional(
    cred: HTTPAuthorizationCredentials = Depends(_security),
) -> User | None:
    """可选鉴权：匿名返回 None，不抛异常（兼容旧 /api/chat）。"""
    if cred is None or not cred.credentials:
        return None
    try:
        payload = decode_token(cred.credentials)
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    user = await _load_user(payload.get("sub", ""))
    if not user or not user.is_active:
        return None
    set_actor(_actor_from(user))
    return user
