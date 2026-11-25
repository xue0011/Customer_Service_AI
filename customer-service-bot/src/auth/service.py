"""用户/令牌服务：登录、刷新、初始化管理员、顾客注册。"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import jwt
from loguru import logger
from sqlalchemy import insert, select

from ..config.settings import get_config
from ..database.db import get_session_factory
from ..database.models import RefreshToken, User
from ..database.repositories_async import UserRepository
from .jwt import create_access_token, create_refresh_token, decode_token
from .models import TokenResponse
from .passwords import hash_password, verify_password


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_tokens(user: User) -> TokenResponse:
    access = create_access_token(user.id, user.role, user.customer_id)
    refresh = create_refresh_token(user.id)
    cfg = get_config().jwt
    exp = datetime.now(UTC) + timedelta(days=cfg.refresh_expire_days)
    factory = get_session_factory()
    async with factory() as s:
        await s.execute(
            insert(RefreshToken).values(
                user_id=user.id,
                token_hash=_hash_token(refresh),
                expires_at=exp,
                revoked=False,
            )
        )
        await s.commit()
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        role=user.role,
        user_id=user.id,
        display_name=user.display_name,
        customer_id=user.customer_id,
    )


async def authenticate(username: str, password: str) -> TokenResponse | None:
    factory = get_session_factory()
    async with factory() as s:
        repo = UserRepository(s)
        user = await repo.get_by_username(username)
    if not user or not user.password_hash:
        return None
    if not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return await issue_tokens(user)


async def refresh_access(refresh_token: str) -> TokenResponse | None:
    try:
        payload = decode_token(refresh_token)
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "refresh":
        return None
    h = _hash_token(refresh_token)
    factory = get_session_factory()
    async with factory() as s:
        r = await s.execute(select(RefreshToken).where(RefreshToken.token_hash == h))
        rt = r.scalar_one_or_none()
        if not rt or rt.revoked or rt.expires_at < datetime.now(UTC):
            return None
        repo = UserRepository(s)
        user = await repo.get_by_id(rt.user_id)
    if not user or not user.is_active:
        return None
    return await issue_tokens(user)


async def ensure_super_user() -> None:
    """首次启动创建管理员（按 RBACConfig）。"""
    cfg = get_config().rbac
    factory = get_session_factory()
    async with factory() as s:
        repo = UserRepository(s)
        user = await repo.get_by_username(cfg.superuser_username)
        pw = cfg.superuser_password.get_secret_value()
        if not user:
            if not pw:
                logger.warning("[auth] 未设 INIT_ADMIN_PASSWORD，跳过管理员创建")
                return
            await repo.create_user(
                cfg.superuser_username,
                hash_password(pw),
                role="admin",
                display_name="管理员",
            )
            await s.commit()
            logger.info(f"[auth] 已创建管理员 {cfg.superuser_username}")


async def register_or_get_customer(customer_id: str, name: str = "") -> User:
    """按 customer_id 幂等获取/创建顾客用户。"""
    factory = get_session_factory()
    async with factory() as s:
        repo = UserRepository(s)
        user = await repo.create_customer(customer_id, name)
        await s.commit()
        return user
