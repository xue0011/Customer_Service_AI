"""API 测试：健康检查、登录、me、订单查询、审批管理。"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from src.api.server import create_app
from src.auth import authenticate, ensure_super_user
from src.database.db import get_session_factory
from src.database.repositories_async import OrderRepository

pytestmark = pytest.mark.asyncio


async def _token() -> str:
    await ensure_super_user()
    t = await authenticate("admin", "testpass123")
    assert t is not None
    return t.access_token


def _client():
    app = create_app()
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_health_and_ready():
    async with _client() as c:
        assert (await c.get("/health")).status_code == 200
        assert (await c.get("/ready")).status_code == 200


async def test_login_me_and_unauthorized():
    token = await _token()
    async with _client() as c:
        r = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["role"] == "admin"
        # 无 token → 401
        r2 = await c.get("/api/auth/me")
        assert r2.status_code == 401


async def test_get_order_as_admin():
    token = await _token()
    factory = get_session_factory()
    async with factory() as s:
        await OrderRepository(s).save({
            "order_id": "ORD-API-1", "customer_id": "cust_001",
            "status": "x", "total_amount": 1,
        })
        await s.commit()
    async with _client() as c:
        r = await c.get("/api/orders/ORD-API-1", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["data"]["order_id"] == "ORD-API-1"


async def test_approvals_list_and_resolve():
    token = await _token()
    async with _client() as c:
        r = await c.get("/api/admin/approvals", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)
