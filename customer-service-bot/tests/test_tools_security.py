"""工具层安全测试：归属校验、二次确认、人工审批、幂等、工具审计。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.database.db import get_session_factory
from src.database.models import ToolCallLog
from src.database.repositories_async import OrderRepository
from src.infra.context import Actor, set_actor
from src.tools.modify_order import ModifyOrderTool
from src.tools.order_query import OrderQueryTool
from src.tools.return_apply import ReturnApplyTool

pytestmark = pytest.mark.asyncio


async def _seed_order(order_id: str, customer_id: str, total: float = 300.0) -> None:
    factory = get_session_factory()
    async with factory() as s:
        await OrderRepository(s).save({
            "order_id": order_id,
            "platform": "taobao",
            "customer_id": customer_id,
            "customer_name": customer_id,
            "customer_phone": "13800000000",
            "status": "pending_shipment",
            "status_display": "待发货",
            "total_amount": total,
            "items": [{"base_product_id": "prod_cl_001", "sku": "x", "name": "连衣裙",
                       "color": "红色", "size": "M", "price": 189, "quantity": 1}],
            "timeline": [],
        })
        await s.commit()


async def test_order_query_own_allowed():
    await _seed_order("ORD-SEC-1", "cust_001")
    set_actor(Actor(user_id="u1", role="customer", customer_id="cust_001"))
    r = await OrderQueryTool(data_dir="./data").safe_execute(order_id="ORD-SEC-1")
    assert r["success"] is True


async def test_order_query_other_owner_rejected():
    await _seed_order("ORD-SEC-2", "cust_002")
    set_actor(Actor(user_id="u1", role="customer", customer_id="cust_001"))
    r = await OrderQueryTool(data_dir="./data").safe_execute(order_id="ORD-SEC-2")
    assert r["success"] is False
    assert "归属" in r["error"] or "权限" in r["error"]


async def test_customer_cannot_query_other_customer_id():
    await _seed_order("ORD-SEC-3", "cust_002")
    set_actor(Actor(user_id="u1", role="customer", customer_id="cust_001"))
    r = await OrderQueryTool(data_dir="./data").safe_execute(customer_id="cust_002")
    assert r["success"] is False


async def test_modify_order_requires_confirmation():
    await _seed_order("ORD-SEC-4", "cust_001")
    set_actor(Actor(user_id="u1", role="customer", customer_id="cust_001"))
    r = await ModifyOrderTool(data_dir="./data").safe_execute(order_id="ORD-SEC-4", new_size="L")
    assert r["success"] is True
    assert r["data"]["requires_confirmation"] is True


async def test_modify_order_other_owner_rejected():
    await _seed_order("ORD-SEC-5", "cust_002")
    set_actor(Actor(user_id="u1", role="customer", customer_id="cust_001"))
    r = await ModifyOrderTool(data_dir="./data").safe_execute(order_id="ORD-SEC-5", new_size="L", confirmed=True)
    assert r["success"] is False


async def test_return_apply_manual_approval():
    await _seed_order("ORD-SEC-6", "cust_001", total=300.0)
    set_actor(Actor(user_id="u1", role="customer", customer_id="cust_001"))
    r = await ReturnApplyTool(data_dir="./data").safe_execute(
        order_id="ORD-SEC-6", reason="不想要了", idempotency_key="K-SEC-1"
    )
    assert r["success"] is True
    assert r["data"]["approval_task_id"]          # 高金额 → 人工审批
    assert r["data"]["review_type"] == "manual"


async def test_return_apply_idempotent():
    await _seed_order("ORD-SEC-7", "cust_001", total=300.0)
    set_actor(Actor(user_id="u1", role="customer", customer_id="cust_001"))
    tool = ReturnApplyTool(data_dir="./data")
    r1 = await tool.safe_execute(order_id="ORD-SEC-7", reason="x", idempotency_key="K-SEC-2")
    assert r1["success"] is True
    r2 = await tool.safe_execute(order_id="ORD-SEC-7", reason="x", idempotency_key="K-SEC-2")
    assert r2["success"] is True
    assert r2["data"].get("idempotent") is True


async def test_return_apply_other_owner_rejected():
    await _seed_order("ORD-SEC-8", "cust_002")
    set_actor(Actor(user_id="u1", role="customer", customer_id="cust_001"))
    r = await ReturnApplyTool(data_dir="./data").safe_execute(order_id="ORD-SEC-8", reason="x")
    assert r["success"] is False


async def test_tool_call_audited():
    await _seed_order("ORD-SEC-9", "cust_001")
    set_actor(Actor(user_id="u-admin", role="admin"))  # admin 放行
    await OrderQueryTool(data_dir="./data").safe_execute(order_id="ORD-SEC-9")
    factory = get_session_factory()
    async with factory() as s:
        logs = (await s.execute(select(ToolCallLog).where(ToolCallLog.tool_name == "order_query"))).scalars().all()
    assert len(logs) >= 1
    assert logs[0].actor_role == "admin"


async def test_modify_order_decrements_stock():
    """DB 商品场景：modify_order 应同事务扣减目标规格库存、归还原规格库存。"""
    from src.database.models import ProductVariant
    from src.database.repositories_async import ProductRepository

    factory = get_session_factory()
    async with factory() as s:
        prepo = ProductRepository(s)
        await prepo.save({
            "base_product_id": "PROD-STK", "name": "T", "category": "clothing",
            "available_sizes": ["S", "M"], "available_colors": ["Red"],
            "variants": [
                {"sku": "STK-R-S", "color": "Red", "size": "S", "price": 100, "stock": 5},
                {"sku": "STK-R-M", "color": "Red", "size": "M", "price": 100, "stock": 3},
            ],
        })
        await OrderRepository(s).save({
            "order_id": "ORD-STK", "customer_id": "cust_001", "status": "pending_shipment",
            "status_display": "待发货", "total_amount": 100,
            "items": [{"base_product_id": "PROD-STK", "sku": "STK-R-S", "name": "T",
                       "color": "Red", "size": "S", "price": 100, "quantity": 1}],
        })
        await s.commit()

    set_actor(Actor(user_id="u1", role="customer", customer_id="cust_001"))
    r = await ModifyOrderTool(data_dir="./data").safe_execute(order_id="ORD-STK", new_size="M", confirmed=True)
    assert r["success"] is True, r

    async with factory() as s:
        m = (await s.execute(select(ProductVariant).where(ProductVariant.sku == "STK-R-M"))).scalar_one()
        ss = (await s.execute(select(ProductVariant).where(ProductVariant.sku == "STK-R-S"))).scalar_one()
    assert m.stock == 2   # 3 - 1
    assert ss.stock == 6   # 5 + 1
