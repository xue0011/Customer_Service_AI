"""认证授权测试：密码、JWT、RBAC、登录、初始化管理员。"""

from __future__ import annotations

import pytest

from src.auth import (
    authenticate,
    can,
    create_access_token,
    decode_token,
    ensure_super_user,
    hash_password,
    verify_password,
)

pytestmark = pytest.mark.asyncio


async def test_password_hash_and_verify():
    h = hash_password("s3cret")
    assert h and h != "s3cret"
    assert verify_password("s3cret", h) is True
    assert verify_password("wrong", h) is False
    assert verify_password("", "") is False


async def test_jwt_roundtrip():
    token = create_access_token("user-1", "admin", "cust_001")
    payload = decode_token(token)
    assert payload["sub"] == "user-1"
    assert payload["role"] == "admin"
    assert payload["customer_id"] == "cust_001"
    assert payload["type"] == "access"


async def test_rbac_permissions():
    assert can("admin", "anything:whatever") is True          # 通配
    assert can("customer", "order:read:own") is True
    assert can("agent", "order:read:any") is True
    assert can("customer", "order:read:any") is False          # 顾客不可读任意
    assert can("lead", "approval:escalate") is True
    assert can("agent", "approval:escalate") is False


async def test_ensure_super_user_and_login():
    await ensure_super_user()
    # 第二次应幂等
    await ensure_super_user()
    token = await authenticate("admin", "testpass123")
    assert token is not None
    assert token.role == "admin"
    assert token.access_token

    bad = await authenticate("admin", "wrong-password")
    assert bad is None
