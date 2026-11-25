"""把 data/ 示例数据灌入 PostgreSQL（首次部署 / 演示用）。

灌入 orders + customers + products + logistics + refunds。
初始管理员由 auth.ensure_super_user 创建，不在此处。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from .db import get_session_factory
from .models import Logistics as LogisticsModel
from .models import Refund as RefundModel
from .repositories_async import (
    OrderRepository,
    ProductRepository,
    UserRepository,
)


async def seed_demo_data(data_dir: str = "./data") -> dict[str, int]:
    """加载 data/ 示例数据到数据库。返回统计。"""
    stats: dict[str, int] = {"orders": 0, "customers": 0, "products": 0, "logistics": 0, "refunds": 0}
    base = Path(data_dir)
    factory = get_session_factory()
    async with factory() as session:
        urepo = UserRepository(session)
        orepo = OrderRepository(session)
        prepo = ProductRepository(session)
        seen: set[str] = set()

        # orders + customers
        orders_dir = base / "orders"
        if orders_dir.exists():
            for f in sorted(orders_dir.glob("*.json")):
                try:
                    order: dict[str, Any] = json.loads(f.read_text(encoding="utf-8"))
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[seed] 跳过 {f.name}: {e}")
                    continue
                cid = order.get("customer_id", "")
                if cid and cid not in seen:
                    await urepo.create_customer(cid, order.get("customer_name", ""))
                    seen.add(cid)
                    stats["customers"] += 1
                try:
                    await orepo.save(order)
                    stats["orders"] += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[seed] 订单 {order.get('order_id')} 写入失败: {e}")

        # products
        products_dir = base / "products"
        if products_dir.exists():
            for f in sorted(products_dir.glob("*.json")):
                try:
                    product: dict[str, Any] = json.loads(f.read_text(encoding="utf-8"))
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[seed] 跳过 {f.name}: {e}")
                    continue
                try:
                    await prepo.save(product)
                    stats["products"] += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[seed] 产品 {product.get('base_product_id')} 写入失败: {e}")

        # logistics
        logistics_dir = base / "logistics"
        if logistics_dir.exists():
            for f in sorted(logistics_dir.glob("*.json")):
                try:
                    rec: dict[str, Any] = json.loads(f.read_text(encoding="utf-8"))
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[seed] 跳过 {f.name}: {e}")
                    continue
                try:
                    existing = await session.get(LogisticsModel, rec["tracking_no"])
                    if existing is None:
                        session.add(LogisticsModel(
                            tracking_no=rec["tracking_no"], order_id=rec.get("order_id"),
                            company=rec.get("company"), company_code=rec.get("company_code"),
                            status=rec.get("status"), current_location=rec.get("current_location"),
                            origin=rec.get("origin"), destination=rec.get("destination"),
                            tracking_history=rec.get("tracking_history"), signed_by=rec.get("signed_by"),
                        ))
                    stats["logistics"] += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[seed] 物流 {rec.get('tracking_no')} 写入失败: {e}")

        # refunds
        refunds_dir = base / "refunds"
        if refunds_dir.exists():
            for f in sorted(refunds_dir.glob("*.json")):
                try:
                    rec = json.loads(f.read_text(encoding="utf-8"))
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[seed] 跳过 {f.name}: {e}")
                    continue
                try:
                    existing = await session.get(RefundModel, rec["refund_id"])
                    if existing is None:
                        session.add(RefundModel(
                            refund_id=rec["refund_id"], order_id=rec.get("order_id"),
                            status=rec.get("status"), status_display=rec.get("status_display"),
                            amount=rec.get("amount"), reason=rec.get("reason"), type=rec.get("type"),
                            stages=rec.get("stages"), refund_channel=rec.get("refund_channel"),
                        ))
                    stats["refunds"] += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[seed] 退款 {rec.get('refund_id')} 写入失败: {e}")

        await session.commit()

    logger.info(f"[seed] 完成: {stats}")
    return stats


async def seed_demo_users() -> dict[str, int]:
    """创建演示用户：管理员(admin) + 顾客(cust_001) + 坐席(agent)。"""
    from ..auth.passwords import hash_password

    stats = {"users": 0}
    factory = get_session_factory()
    async with factory() as s:
        urepo = UserRepository(s)
        await urepo.create_customer("cust_001", "小明")  # 幂等
        stats["users"] += 1
        if not await urepo.get_by_username("agent"):
            await urepo.create_user(
                "agent", hash_password("demo123456"),
                role="agent", display_name="演示坐席",
            )
            stats["users"] += 1
        await s.commit()
    logger.info(f"[seed] 演示用户完成: {stats}")
    return stats


if __name__ == "__main__":
    import asyncio

    async def _run():
        await seed_demo_data()
        await seed_demo_users()

    asyncio.run(_run())

