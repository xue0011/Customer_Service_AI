"""
物流查询工具
───────────
P0：归属校验。按订单号查询需校验订单归属；按快递单号查询仅员工可用。
物流明细仍读 JSON（P1 迁入 PG）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from .base import BaseTool
from .security import check_order_ownership


class LogisticsQueryTool(BaseTool):
    """物流查询工具 —— 查询包裹的物流详情。"""

    required_permission = None

    def __init__(self, data_dir: str = "./data", logistics_repo=None) -> None:
        super().__init__()
        self._data_dir = Path(data_dir)
        self._logistics_dir = self._data_dir / "logistics"
        self._logistics_repo = logistics_repo
        self._logistics: dict[str, dict[str, Any]] = {}
        self._by_order: dict[str, str] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if not self._logistics_dir.exists():
            self._loaded = True
            return
        for fpath in self._logistics_dir.glob("*.json"):
            try:
                record = json.loads(fpath.read_text(encoding="utf-8"))
                self._logistics[record["tracking_no"]] = record
                if record.get("order_id"):
                    self._by_order[record["order_id"]] = record["tracking_no"]
            except Exception:  # noqa: BLE001
                logger.exception(f"[Logistics] 加载失败: {fpath}")
        self._loaded = True
        logger.info(f"[Logistics] 从 JSON 加载了 {len(self._logistics)} 条物流记录")

    @property
    def name(self) -> str:
        return "logistics_query"

    @property
    def description(self) -> str:
        return "查询物流详情。可按订单号查询（受归属校验）。按快递单号查询仅员工可用。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号"},
                "tracking_no": {"type": "string", "description": "快递单号"},
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        from ..infra.context import get_actor

        order_id = kwargs.get("order_id", "")
        tracking_no = kwargs.get("tracking_no", "")
        actor = get_actor()

        if order_id:
            order = await self._fetch_order(order_id)
            if order:
                check_order_ownership(order)
        elif tracking_no:
            if actor is not None and not actor.is_staff():
                return {"success": False, "error": "按快递单号查询仅限客服人员；顾客请使用订单号查询。"}
        else:
            return {"success": False, "error": "请提供订单号或快递单号"}

        # 优先 DB 查物流
        try:
            from ..database.db import get_session_factory
            from ..database.repositories_async import LogisticsRepository

            async with get_session_factory()() as s:
                lrepo = LogisticsRepository(s)
                if order_id:
                    rec = await lrepo.get_by_order(order_id)
                else:
                    rec = await lrepo.get_by_tracking(tracking_no)
                if rec:
                    return {"success": True, "data": rec}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[Logistics] DB 不可用，回退 JSON：{e}")
        self._load()
        return await self._execute_json(order_id, tracking_no)

    async def _fetch_order(self, order_id: str) -> dict[str, Any] | None:
        try:
            from ..database.db import get_session_factory
            from ..database.repositories_async import OrderRepository as AsyncRepo

            async with get_session_factory()() as s:
                return await AsyncRepo(s).get_by_id(order_id)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Logistics] DB 不可用，JSON 回退查归属：{e}")
            p = self._data_dir / "orders" / f"{order_id}.json"
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    return None
            return None

    async def _execute_json(self, order_id: str, tracking_no: str) -> dict[str, Any]:
        if order_id:
            tracking_no = self._by_order.get(order_id, "")
            if not tracking_no:
                return {"success": True, "data": None, "message": f"未找到订单 {order_id} 的物流信息，可能尚未发货"}
        if tracking_no:
            record = self._logistics.get(tracking_no)
            if not record:
                return {"success": True, "data": None, "message": f"未找到快递单号 {tracking_no} 的物流信息"}
            return {"success": True, "data": record}
        return {"success": False, "error": "请提供订单号或快递单号"}
