"""
订单查询工具
───────────
P0：PostgreSQL 优先（异步仓储），JSON 回退。
验收5：所有查询校验调用者身份与订单归属（IDOR 防护）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from .base import BaseTool
from .security import assert_customer_matches, check_order_ownership


class OrderQueryTool(BaseTool):
    """订单查询工具 —— 查询订单的详细信息。"""

    required_permission = None  # 顾客查自有、员工查任意，由归属校验把关

    def __init__(self, data_dir: str = "./data", order_repo=None) -> None:
        super().__init__()
        self._orders_dir = Path(data_dir) / "orders"
        self._order_repo = order_repo  # legacy，未使用（保留兼容签名）
        self._orders: dict[str, dict[str, Any]] = {}
        self._by_customer: dict[str, list[str]] = {}
        self._by_phone: dict[str, str] = {}
        self._loaded = False

    def _load_orders(self) -> None:
        if self._loaded:
            return
        if not self._orders_dir.exists():
            self._loaded = True
            return
        for fpath in self._orders_dir.glob("*.json"):
            try:
                order = json.loads(fpath.read_text(encoding="utf-8"))
                oid = order["order_id"]
                self._orders[oid] = order
                cid = order.get("customer_id", "")
                self._by_customer.setdefault(cid, []).append(oid)
                phone = order.get("customer_phone", "")
                if phone:
                    self._by_phone[phone] = oid
            except Exception:  # noqa: BLE001
                logger.exception(f"[OrderQuery] 加载订单失败: {fpath}")
        self._loaded = True
        logger.info(f"[OrderQuery] 从 JSON 加载了 {len(self._orders)} 个订单")

    @property
    def name(self) -> str:
        return "order_query"

    @property
    def description(self) -> str:
        return (
            "查询订单信息（状态、商品、金额、时间线）。"
            "可按订单号或顾客ID查询。查询结果受调用者身份与订单归属校验限制："
            "顾客仅可查询本人订单。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号，如 ORD-20260715-001"},
                "customer_id": {"type": "string", "description": "顾客ID，如 cust_001"},
                "query_type": {
                    "type": "string",
                    "enum": ["status", "items", "all"],
                    "description": "查询类型",
                    "default": "all",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        order_id = kwargs.get("order_id", "")
        customer_id = kwargs.get("customer_id", "")
        query_type = kwargs.get("query_type", "all")

        if customer_id:
            assert_customer_matches(customer_id)
        if not (order_id or customer_id):
            return {"success": False, "error": "请提供订单号或顾客ID"}

        # 优先 PG，查询为空或异常时回退 JSON
        orders: Any = None
        try:
            orders = await self._fetch_db(order_id, customer_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[OrderQuery] DB 不可用，回退 JSON：{e}")
        if not orders:
            self._load_orders()
            orders = self._fetch_json(order_id, customer_id)

        if not orders:
            return {"success": True, "data": None, "message": "未找到订单"}

        if isinstance(orders, list):
            for o in orders:
                check_order_ownership(o)
            data = [self._filter_order(o, query_type) for o in orders]
            return {"success": True, "data": data, "count": len(data)}
        check_order_ownership(orders)
        return {"success": True, "data": self._filter_order(orders, query_type)}

    async def _fetch_db(self, order_id: str, customer_id: str) -> Any:
        from ..database.db import get_session_factory
        from ..database.repositories_async import OrderRepository as AsyncRepo

        async with get_session_factory()() as s:
            repo = AsyncRepo(s)
            if order_id:
                return await repo.get_by_id(order_id)
            if customer_id:
                return await repo.get_by_customer(customer_id)
        return None

    def _fetch_json(self, order_id: str, customer_id: str) -> Any:
        if order_id:
            return self._orders.get(order_id)
        if customer_id:
            return [self._orders[oid] for oid in self._by_customer.get(customer_id, []) if oid in self._orders]
        return None

    def _filter_order(self, order: dict[str, Any], query_type: str) -> dict[str, Any]:
        if query_type == "status":
            return {
                "order_id": order["order_id"],
                "platform": order.get("platform"),
                "status": order["status"],
                "status_display": order.get("status_display"),
                "timeline": order.get("timeline", []),
                "total_amount": order.get("total_amount"),
            }
        if query_type == "items":
            return {
                "order_id": order["order_id"],
                "items": order.get("items", []),
                "total_amount": order.get("total_amount"),
            }
        # 脱敏：对外不直接暴露完整 customer_phone
        out = dict(order)
        if "customer_phone" in out and out["customer_phone"]:
            p = str(out["customer_phone"])
            out["customer_phone"] = p[:3] + "****" + p[-4:] if len(p) >= 7 else p
        return out
