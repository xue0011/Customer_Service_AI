"""订单查询工具测试（P0：DB 优先、JSON 回退；归属由 admin Actor 放行）。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.tools.order_query import OrderQueryTool


@pytest.fixture
def data_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        orders_dir = Path(tmpdir) / "orders"
        orders_dir.mkdir()
        orders = [
            {"order_id": "ORD-001", "customer_id": "cust_001", "customer_phone": "13800001111",
             "status": "pending_shipment", "status_display": "pending", "total_amount": 399.00,
             "platform": "taobao", "items": [{"sku": "SKU-001", "name": "Test Product"}], "timeline": []},
            {"order_id": "ORD-002", "customer_id": "cust_001", "customer_phone": "13800002222",
             "status": "shipped", "status_display": "shipped", "total_amount": 159.00,
             "platform": "pinduoduo", "items": [{"sku": "SKU-002", "name": "B"}], "timeline": []},
            {"order_id": "ORD-003", "customer_id": "cust_002", "customer_phone": "13900003333",
             "status": "delivered", "status_display": "delivered", "total_amount": 599.00,
             "platform": "jd", "items": [{"sku": "SKU-003", "name": "C"}], "timeline": []},
        ]
        for o in orders:
            (orders_dir / f"{o['order_id']}.json").write_text(json.dumps(o), encoding="utf-8")
        yield tmpdir


class TestOrderQuery:
    @pytest.mark.asyncio
    async def test_query_by_order_id(self, data_dir):
        r = await OrderQueryTool(data_dir=data_dir).execute(order_id="ORD-001")
        assert r["success"] is True
        assert r["data"]["order_id"] == "ORD-001"

    @pytest.mark.asyncio
    async def test_query_by_customer_id(self, data_dir):
        r = await OrderQueryTool(data_dir=data_dir).execute(customer_id="cust_001")
        assert r["success"] is True
        assert r["count"] == 2

    @pytest.mark.asyncio
    async def test_query_not_found(self, data_dir):
        r = await OrderQueryTool(data_dir=data_dir).execute(order_id="ORD-NONEXISTENT")
        assert r["data"] is None

    @pytest.mark.asyncio
    async def test_query_no_params(self, data_dir):
        r = await OrderQueryTool(data_dir=data_dir).execute()
        assert r["success"] is False

    @pytest.mark.asyncio
    async def test_query_type_filter(self, data_dir):
        r = await OrderQueryTool(data_dir=data_dir).execute(order_id="ORD-001", query_type="status")
        assert r["success"] is True
        assert "status" in r["data"]
        assert "items" not in r["data"]
