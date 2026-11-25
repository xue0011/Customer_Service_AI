"""端到端集成测试：登录 → RAG 上传 → 退款 FSM → metrics（验收9）。"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from src.api.server import create_app
from src.auth import authenticate, ensure_super_user
from src.database.db import get_session_factory
from src.database.repositories_async import RefundRequestRepository

pytestmark = pytest.mark.asyncio


async def _token() -> str:
    await ensure_super_user()
    t = await authenticate("admin", "testpass123")
    assert t is not None
    return t.access_token


def _client():
    return httpx.AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


async def test_e2e_login_rag_refund_metrics():
    token = await _token()
    auth = {"Authorization": f"Bearer {token}"}

    async with _client() as c:
        # 1) 健康 + 当前用户
        assert (await c.get("/health")).status_code == 200
        me = await c.get("/api/auth/me", headers=auth)
        assert me.status_code == 200
        assert me.json()["role"] == "admin"

        # 2) RAG 文档上传 + 列表
        up = await c.post("/api/admin/rag/documents", json={
            "content": "7天无理由退货，商品需保持完好，标签完整。",
            "category": "policy", "title": "退货政策", "source": "e2e",
        }, headers=auth)
        assert up.status_code == 200
        doc_id = up.json()["document_id"]
        lst = await c.get("/api/admin/rag/documents", headers=auth)
        assert lst.json()["count"] >= 1
        assert any(d["id"] == doc_id for d in lst.json()["data"])

        # 3) 退款 FSM：创建 → 合法转换 → 非法转换被拒
        factory = get_session_factory()
        async with factory() as s:
            await RefundRequestRepository(s).create({
                "id": "REF-E2E", "order_id": "ORD-E2E", "customer_id": "c1",
                "status": "submitted", "current_stage": "submitted",
                "type": "return", "amount": 100, "reason": "x",
            })
            await s.commit()

        tr = await c.post("/api/admin/refunds/REF-E2E/transition",
                          json={"to": "under_review", "note": "审核"}, headers=auth)
        assert tr.status_code == 200
        assert tr.json()["status"] == "under_review"

        bad = await c.post("/api/admin/refunds/REF-E2E/transition",
                           json={"to": "refunded"}, headers=auth)  # 非法跳转
        assert bad.status_code == 400

        # 4) 改地址审批
        ac = await c.post("/api/admin/address-changes",
                          json={"order_id": "ORD-E2E", "old_address": {"city": "杭州"},
                                "new_address": {"city": "上海"}}, headers=auth)
        assert ac.status_code == 200
        assert ac.json()["status"] == "requested"

        # 5) metrics（若 instrumentator 已安装）
        m = await c.get("/metrics")
        assert m.status_code in (200, 404)
