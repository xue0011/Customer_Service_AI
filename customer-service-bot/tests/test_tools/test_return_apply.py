"""退货申请工具测试（P0：审批 FSM；检查不通过→人工复核；JSON 回退）。"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.tools.return_apply import ReturnApplyTool


@pytest.fixture
def data_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        products_dir = Path(tmpdir) / "products"
        products_dir.mkdir()
        product = {"base_product_id": "PROD-001", "name": "Test", "category": "clothing",
                   "is_returnable": True, "tags_attached_by_default": True, "returnable_category": "clothing",
                   "variants": [{"sku": "SKU-001", "color": "Red", "size": "M", "price": 150.00, "stock": 10}]}
        (products_dir / "prod_001.json").write_text(json.dumps(product), encoding="utf-8")

        policies_dir = Path(tmpdir) / "policies"
        policies_dir.mkdir()
        policy = {"policy_name": "Return Policy", "non_returnable_categories": ["custom", "fresh_food"],
                  "return_address": {"name": "Returns", "address": "123", "phone": "123"}}
        (policies_dir / "return_policy.json").write_text(json.dumps(policy), encoding="utf-8")

        orders_dir = Path(tmpdir) / "orders"
        orders_dir.mkdir()
        now = datetime.now(UTC)
        recent = (now - timedelta(days=2)).isoformat()
        old = (now - timedelta(days=10)).isoformat()

        def mk(oid, cid, total, price, delivered):
            return {"order_id": oid, "customer_id": cid, "customer_name": cid,
                    "customer_phone": "13800000000", "status": "delivered", "status_display": "delivered",
                    "total_amount": total,
                    "items": [{"sku": "SKU-001", "base_product_id": "PROD-001", "name": "Test",
                               "color": "Red", "size": "M", "price": price, "quantity": 1}],
                    "timeline": [{"time": delivered, "event": "已签收"}],
                    "delivered_at": delivered, "created_at": delivered}

        for o in [
            mk("ORD-SMALL", "cust_001", 150.00, 150.00, recent),
            mk("ORD-LARGE", "cust_002", 399.00, 399.00, recent),
            mk("ORD-OLD", "cust_003", 150.00, 150.00, old),
            mk("ORD-BOUNDARY", "cust_004", 199.99, 199.99, recent),
            mk("ORD-BOUNDARY2", "cust_005", 200.00, 200.00, recent),
        ]:
            (orders_dir / f"{o['order_id']}.json").write_text(json.dumps(o), encoding="utf-8")
        yield tmpdir


class TestReturnApply:
    @pytest.mark.asyncio
    async def test_small_auto_approve(self, data_dir):
        r = await ReturnApplyTool(data_dir=data_dir).execute(order_id="ORD-SMALL", reason="Wrong size")
        assert r["success"] is True
        assert r["data"]["approved"] is True
        assert r["data"]["review_type"] == "auto"

    @pytest.mark.asyncio
    async def test_large_manual_review(self, data_dir):
        r = await ReturnApplyTool(data_dir=data_dir).execute(order_id="ORD-LARGE", reason="Wrong color")
        assert r["success"] is True
        assert r["data"]["review_type"] == "manual"
        assert r["data"]["approval_task_id"]

    @pytest.mark.asyncio
    async def test_old_order_manual_review(self, data_dir):
        # 超过 7 天窗口 → 检查不通过 → 走人工复核（非直接拒绝）
        r = await ReturnApplyTool(data_dir=data_dir).execute(order_id="ORD-OLD", reason="No longer want")
        assert r["success"] is True
        assert r["data"]["review_type"] == "manual"

    @pytest.mark.asyncio
    async def test_boundary_199_auto(self, data_dir):
        r = await ReturnApplyTool(data_dir=data_dir).execute(order_id="ORD-BOUNDARY", reason="x")
        assert r["data"]["review_type"] == "auto"

    @pytest.mark.asyncio
    async def test_boundary_200_manual(self, data_dir):
        r = await ReturnApplyTool(data_dir=data_dir).execute(order_id="ORD-BOUNDARY2", reason="x")
        assert r["data"]["review_type"] == "manual"

    @pytest.mark.asyncio
    async def test_missing_order_id(self, data_dir):
        r = await ReturnApplyTool(data_dir=data_dir).execute(reason="x")
        assert r["success"] is False

    @pytest.mark.asyncio
    async def test_missing_reason(self, data_dir):
        r = await ReturnApplyTool(data_dir=data_dir).execute(order_id="ORD-SMALL")
        assert r["success"] is False
