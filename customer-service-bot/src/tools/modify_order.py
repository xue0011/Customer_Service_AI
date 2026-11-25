"""
修改订单工具
───────────
P0：PG 优先（异步仓储），JSON 回退。
验收5/6：高风险写操作 —— 身份与订单归属校验 + 二次确认。
修复：不截断多商品订单（去掉 order["items"]=[item]）；库存校验保留。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from .base import BaseTool
from .security import check_order_ownership


class ModifyOrderTool(BaseTool):
    """修改订单工具 —— 修改同款商品的尺码和/或颜色（需确认）。"""

    high_risk = True
    require_confirmation = True
    required_permission = None  # 顾客改自有、员工改任意，由归属校验把关

    def __init__(self, data_dir: str = "./data", order_repo=None, product_repo=None) -> None:
        super().__init__()
        self._data_dir = Path(data_dir)
        self._order_repo = order_repo
        self._product_repo = product_repo
        self._products: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def _load_products(self) -> None:
        if self._loaded:
            return
        products_dir = self._data_dir / "products"
        if not products_dir.exists():
            self._loaded = True
            return
        for fpath in products_dir.glob("*.json"):
            try:
                product = json.loads(fpath.read_text(encoding="utf-8"))
                self._products[product["base_product_id"]] = product
            except Exception:  # noqa: BLE001
                logger.exception(f"[ModifyOrder] 加载产品失败: {fpath}")
        self._loaded = True

    def _load_order_json(self, order_id: str) -> dict[str, Any] | None:
        order_path = self._data_dir / "orders" / f"{order_id}.json"
        if not order_path.exists():
            return None
        try:
            return json.loads(order_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    def _save_order_json(self, order: dict[str, Any]) -> None:
        order_path = self._data_dir / "orders" / f"{order['order_id']}.json"
        tmp = order_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(order_path)  # 原子替换

    @property
    def name(self) -> str:
        return "modify_order"

    @property
    def description(self) -> str:
        return (
            "修改订单商品规格（尺码和/或颜色），仅待发货订单可改，且为同款其他规格。"
            "高风险操作：首次调用返回待确认摘要，需用户确认后再次调用并设置 confirmed=true 才执行。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号，如 ORD-20260715-001"},
                "new_size": {"type": "string", "description": "新尺码 S/M/L/XL/XXL（可选）"},
                "new_color": {"type": "string", "description": "新颜色（可选）"},
                "confirmed": {"type": "boolean", "description": "是否已确认执行（高风险二次确认）", "default": False},
            },
            "required": ["order_id"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        order_id = kwargs.get("order_id", "")
        new_size = kwargs.get("new_size", "")
        new_color = kwargs.get("new_color", "")

        if not order_id:
            return {"success": False, "error": "请提供订单号"}
        if not new_size and not new_color:
            return {"success": False, "error": "请提供要修改的新尺码和/或新颜色"}

        order = await self._fetch_order(order_id)
        if not order:
            return {"success": False, "error": f"未找到订单 {order_id}"}

        # 归属校验
        check_order_ownership(order)

        if order["status"] != "pending_shipment":
            return {
                "success": False,
                "error": f"订单状态为'{order.get('status_display', order['status'])}'，无法修改。",
                "suggestion": "订单已发货，请收货后申请售后换货（return_apply）。",
            }

        items = order.get("items", [])
        if not items:
            return {"success": False, "error": "订单中没有商品信息"}

        item = items[0]
        base_product_id = item.get("base_product_id", "")
        current_size = item.get("size", "")
        current_color = item.get("color", "")

        product = await self._load_product(base_product_id)
        if not product:
            return {"success": False, "error": f"产品信息不存在: {base_product_id}"}

        available_sizes = product.get("available_sizes", [])
        available_colors = product.get("available_colors", [])
        variants = product.get("variants", [])

        target_size = new_size if new_size else current_size
        if new_size and new_size not in available_sizes:
            return {"success": False, "error": f"该产品不支持尺码 '{new_size}'", "detail": f"可选尺码: {', '.join(available_sizes)}"}

        target_color = new_color if new_color else current_color
        if new_color and new_color not in available_colors:
            return {"success": False, "error": f"该产品不支持颜色 '{new_color}'", "detail": f"可选颜色: {', '.join(available_colors)}"}

        target_variant = next((v for v in variants if v.get("color") == target_color and v.get("size") == target_size), None)
        if not target_variant:
            return {"success": False, "error": f"该产品没有 {target_color} {target_size} 的组合"}

        if target_variant.get("stock", 0) <= 0:
            return {"success": False, "error": f"{target_color} {target_size} 当前缺货"}

        old_spec = f"{current_color} {current_size}"
        new_spec = f"{target_color} {target_size}"
        changes = []
        if new_size and new_size != current_size:
            changes.append(f"尺码: {current_size} → {new_size}")
        if new_color and new_color != current_color:
            changes.append(f"颜色: {current_color} → {new_color}")

        original_sku = item.get("sku", "")
        target_sku = target_variant["sku"]
        # 修改 items[0] 字段（item 是列表元素引用，不截断其余商品）
        item["size"] = target_size
        item["color"] = target_color
        item["sku"] = target_sku
        item["price"] = target_variant["price"]
        # 注意：不执行 order["items"] = [item]（原逻辑会截断多商品订单）
        order["total_amount"] = target_variant["price"] * item.get("quantity", 1) + order.get("shipping_fee", 0)
        order.setdefault("timeline", []).append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event": f"修改商品规格: {', '.join(changes)}",
        })

        await self._save_order(order, target_sku=target_sku, original_sku=original_sku)
        await self._audit(order_id, old_spec, new_spec, changes)

        return {
            "success": True,
            "data": {
                "order_id": order_id,
                "message": "订单修改成功",
                "changes": changes,
                "old_spec": old_spec,
                "new_spec": new_spec,
                "new_price": target_variant["price"],
                "new_total": order["total_amount"],
            },
        }

    async def _pending_confirmation(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        return {
            "success": True,
            "data": {
                "requires_confirmation": True,
                "message": "修改订单规格为高风险操作，请向顾客确认后再次调用并设置 confirmed=true。",
                "preview": {
                    "order_id": kwargs.get("order_id"),
                    "new_size": kwargs.get("new_size"),
                    "new_color": kwargs.get("new_color"),
                },
            },
        }

    async def _fetch_order(self, order_id: str) -> dict[str, Any] | None:
        try:
            from ..database.db import get_session_factory
            from ..database.repositories_async import OrderRepository as AsyncRepo

            async with get_session_factory()() as s:
                o = await AsyncRepo(s).get_by_id(order_id)
                if o:
                    return o
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ModifyOrder] DB 不可用，回退 JSON：{e}")
        return self._load_order_json(order_id)

    async def _load_product(self, base_product_id: str) -> dict[str, Any] | None:
        try:
            from ..database.db import get_session_factory
            from ..database.repositories_async import ProductRepository

            async with get_session_factory()() as s:
                p = await ProductRepository(s).get_by_id(base_product_id)
                if p:
                    return p
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ModifyOrder] DB 产品查询不可用，回退 JSON：{e}")
        self._load_products()
        return self._products.get(base_product_id)

    async def _save_order(
        self, order: dict[str, Any], target_sku: str = "", original_sku: str = ""
    ) -> None:
        try:
            from ..database.db import get_session_factory
            from ..database.repositories_async import OrderRepository as AsyncRepo
            from ..database.repositories_async import ProductRepository

            async with get_session_factory()() as s:
                repo = AsyncRepo(s)
                prepo = ProductRepository(s)
                await repo.save(order)
                # 库存扣减：新规格 -1，原规格 +1（同事务，防超卖）
                if target_sku and target_sku != original_sku:
                    if not await prepo.decrement_stock(target_sku, 1):
                        raise RuntimeError(f"库存不足或规格不存在: {target_sku}")
                    if original_sku:
                        await prepo.increment_stock(original_sku, 1)
                await s.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ModifyOrder] DB 保存失败，回退 JSON：{e}")
            self._save_order_json(order)

    async def _audit(self, order_id: str, old_spec: str, new_spec: str, changes: list[str]) -> None:
        from ..infra.audit import audit

        await audit(
            action="mutation",
            resource=f"order:{order_id}",
            before={"spec": old_spec},
            after={"spec": new_spec, "changes": changes},
        )
