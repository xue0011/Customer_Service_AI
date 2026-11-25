"""数据层测试：ORM 建表、仓储 CRUD、乐观锁。"""

from __future__ import annotations

import pytest

from src.database.db import get_session_factory
from src.database.repositories_async import (
    ApprovalRepository,
    AuditRepository,
    OrderRepository,
    RefundRequestRepository,
    UserRepository,
)

pytestmark = pytest.mark.asyncio


async def test_order_save_and_get():
    factory = get_session_factory()
    async with factory() as s:
        repo = OrderRepository(s)
        await repo.save({
            "order_id": "ORD-T-1",
            "platform": "taobao",
            "customer_id": "cust_001",
            "customer_name": "小明",
            "customer_phone": "13800138000",
            "status": "pending_shipment",
            "status_display": "待发货",
            "total_amount": 199,
            "items": [{"name": "连衣裙", "quantity": 1}],
        })
        await s.commit()

    async with factory() as s:
        o = await OrderRepository(s).get_by_id("ORD-T-1")
    assert o is not None
    assert o["order_id"] == "ORD-T-1"
    assert o["customer_id"] == "cust_001"
    assert o["total_amount"] == 199


async def test_get_by_customer_and_phone():
    factory = get_session_factory()
    async with factory() as s:
        repo = OrderRepository(s)
        await repo.save({"order_id": "ORD-T-2", "customer_id": "cust_002",
                          "customer_phone": "13900000000", "status": "x", "total_amount": 10})
        await s.commit()
    async with factory() as s:
        repo = OrderRepository(s)
        by_c = await repo.get_by_customer("cust_002")
        by_p = await repo.get_by_phone("13900000000")
    assert len(by_c) == 1 and by_c[0]["order_id"] == "ORD-T-2"
    assert len(by_p) == 1 and by_p[0]["order_id"] == "ORD-T-2"


async def test_optimistic_lock():
    factory = get_session_factory()
    async with factory() as s:
        await OrderRepository(s).save({"order_id": "ORD-LK", "customer_id": "c1", "status": "s0", "version": 1})
        await s.commit()
    # 正确版本更新 → 成功
    async with factory() as s:
        await OrderRepository(s).save({"order_id": "ORD-LK", "customer_id": "c1", "status": "s1", "version": 1})
        await s.commit()
    # 过期版本（1）应冲突
    with pytest.raises(RuntimeError):
        async with factory() as s:
            await OrderRepository(s).save({"order_id": "ORD-LK", "customer_id": "c1", "status": "s2", "version": 1})
            await s.commit()


async def test_user_and_refund_and_approval_and_audit():
    factory = get_session_factory()
    async with factory() as s:
        urepo = UserRepository(s)
        u = await urepo.create_customer("cust_001", "小明")
        assert u.customer_id == "cust_001"

        rrepo = RefundRequestRepository(s)
        rr = await rrepo.create({
            "id": "REF-T-1", "order_id": "ORD-T-1", "customer_id": "cust_001",
            "type": "return", "amount": 199, "reason": "不想要了", "status": "under_review",
            "current_stage": "submitted",
        })
        assert rr.id == "REF-T-1"

        arepo = ApprovalRepository(s)
        a = await arepo.create({
            "id": "APR-T-1", "request_id": "REF-T-1", "order_id": "ORD-T-1",
            "type": "return", "status": "pending",
        })
        assert a.id == "APR-T-1"

        pending = await arepo.list_pending()
        assert len(pending) == 1

        audit = AuditRepository(s)
        log = await audit.append(actor_id=u.id, actor_role="customer", action="refund:create", resource="order:ORD-T-1")
        assert log.id is not None
        await s.commit()
