"""JWT 签发与校验。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from loguru import logger

from ..config.settings import get_config


def _cfg():
    return get_config().jwt


def create_access_token(user_id: str, role: str, customer_id: str | None = None) -> str:
    cfg = _cfg()
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=cfg.access_expire_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "customer_id": customer_id,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, cfg.secret.get_secret_value(), algorithm=cfg.algorithm)


def create_refresh_token(user_id: str) -> str:
    cfg = _cfg()
    now = datetime.now(UTC)
    exp = now + timedelta(days=cfg.refresh_expire_days)
    payload: dict[str, Any] = {
        "sub": user_id,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, cfg.secret.get_secret_value(), algorithm=cfg.algorithm)


def decode_token(token: str) -> dict[str, Any]:
    cfg = _cfg()
    return jwt.decode(token, cfg.secret.get_secret_value(), algorithms=[cfg.algorithm])


def assert_secret_configured() -> None:
    """启动校验：JWT_SECRET 必须配置且非默认值（生产）。"""
    secret = _cfg().secret.get_secret_value()
    env = get_config().app_env
    if not secret:
        if env == "production":
            raise RuntimeError("生产环境必须设置 JWT_SECRET")
        logger.warning("[auth] JWT_SECRET 未设置（仅开发可运行）")
