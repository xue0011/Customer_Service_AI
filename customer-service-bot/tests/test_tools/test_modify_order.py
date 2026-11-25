"""修改订单工具测试（P0：JSON 回退；admin 放行归属；直接 execute 不触发确认 gate）。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.tools.modify_order import ModifyOrderTool


@pytest.fixture
def data_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        products_dir = Path(tmpdir) / "products"
        products_dir.mkdir()
        product = {
            "base_product_id": "PROD-001", "name": "Test Dress", "category": "clothing",
            "available_sizes": ["S", "M", "L"], "available_colors": ["Red", "Black"],
            "variants": [
                {"sku": "SKU-R-S", "color": "Red", "size": "S", "price": 399.00, "stock": 10},
                {"sku": "SKU-R-M", "color": "Red", "size": "M", "price": 399.00, "stock": 5},
                {"sku": "SKU-B-S", "color": "Black", "size": "S", "price": 399.00, "stock": 8},
            ],
        }
        (products_dir / "prod_001.json").write_text(json.dumps(product), encoding="utf-8")

        orders_dir = Path(tmpdir) / "orders"
        orders_dir.mkdir()
        pending = {"order_id": "ORD-PENDING", "customer_id": "cust_001", "status": "pending_shipment",
                   "status_display": "pending", "total_amount": 399.00, "shipping_fee": 0.00,
                   "items": [{"sku": "SKU-R-S", "base_product_id": "PROD-001", "name": "Test Dress",
                              "color": "Red", "size": "S", "price": 399.00, "quantity": 1}], "timeline": []}
        (orders_dir / "ORD-PENDING.json").write_text(json.dumps(pending), encoding="utf-8")
        shipped = {"order_id": "ORD-SHIPPED", "customer_id": "cust_002", "status": "shipped",
                    "status_display": "shipped", "total_amount": 399.00,
                    "items": [{"sku": "SKU-R-S", "base_product_id": "PROD-001", "name": "Test Dress",
                               "color": "Red", "size": "S", "price": 399.00, "quantity": 1}], "timeline": []}
        (orders_dir / "ORD-SHIPPED.json").write_text(json.dumps(shipped), encoding="utf-8")
        yield tmpdir


class TestModifyOrder:
    @pytest.mark.asyncio
    async def test_modify_size_success(self, data_dir):
        r = await ModifyOrderTool(data_dir=data_dir).execute(order_id="ORD-PENDING", new_size="M")
        assert r["success"] is True

    @pytest.mark.asyncio
    async def test_modify_color_success(self, data_dir):
        r = await ModifyOrderTool(data_dir=data_dir).execute(order_id="ORD-PENDING", new_color="Black")
        assert r["success"] is True

    @pytest.mark.asyncio
    async def test_modify_shipped_rejected(self, data_dir):
        r = await ModifyOrderTool(data_dir=data_dir).execute(order_id="ORD-SHIPPED", new_size="M")
        assert r["success"] is False

    @pytest.mark.asyncio
    async def test_modify_invalid_size_rejected(self, data_dir):
        r = await ModifyOrderTool(data_dir=data_dir).execute(order_id="ORD-PENDING", new_size="XXL")
        assert r["success"] is False

    @pytest.mark.asyncio
    async def test_modify_no_params(self, data_dir):
        r = await ModifyOrderTool(data_dir=data_dir).execute(order_id="ORD-PENDING")
        assert r["success"] is False
