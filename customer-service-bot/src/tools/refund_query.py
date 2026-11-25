"""
退款查询工具
───────────
P0：归属校验。按订单号查询需校验订单归属；按退款单号查询仅员工可用。
退款明细仍读 JSON（P1 迁入 PG）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from .base import BaseTool
from .security import check_order_ownership


class RefundQueryTool(BaseTool):
    """退款查询工具 —— 查询退款/退货的处理进度。"""

    required_permission = None

    def __init__(self, data_dir: str = "./data", refund_repo=None) -> None:
        super().__init__()
        self._data_dir = Path(data_dir)
        self._refunds_dir = self._data_dir / "refunds"
        self._refund_repo = refund_repo
        self._refunds: dict[str, dict[str, Any]] = {}
        self._by_order: dict[str, str] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if not self._refunds_dir.exists():
            self._loaded = True
            return
        for fpath in self._refunds_dir.glob("*.json"):
            try:
                record = json.loads(fpath.read_text(encoding="utf-8"))
                self._refunds[record["refund_id"]] = record
                if record.get("order_id"):
                    self._by_order[record["order_id"]] = record["refund_id"]
            except Exception:  # noqa: BLE001
                logger.exception(f"[Refund] 加载失败: {fpath}")
        self._loaded = True
        logger.info(f"[Refund] 从 JSON 加载了 {len(self._refunds)} 条退款记录")

    @property
    def name(self) -> str:
        return "refund_query"

    @property
    def description(self) -> str:
        return "查询退款/退货处理进度。可按订单号查询（受归属校验）。按退款单号查询仅员工可用。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号"},
                "refund_id": {"type": "string", "description": "退款单号，如 REF-20260715-001"},
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        from ..infra.context import get_actor

        order_id = kwargs.get("order_id", "")
        refund_id = kwargs.get("refund_id", "")
        actor = get_actor()

        if order_id:
            order = await self._fetch_order(order_id)
            if order:
                check_order_ownership(order)
        elif refund_id:
            if actor is not None and not actor.is_staff():
                return {"success": False, "error": "按退款单号查询仅限客服人员；顾客请使用订单号查询。"}
        else:
            return {"success": False, "error": "请提供订单号或退款单号"}

        # 优先 DB 查退款记录
        try:
            from ..database.db import get_session_factory
            from ..database.repositories_async import RefundRepository

            async with get_session_factory()() as s:
                rrepo = RefundRepository(s)
                if order_id:
                    rec = await rrepo.get_by_order(order_id)
                else:
                    rec = await rrepo.get_by_id(refund_id)
                if rec:
                    return {"success": True, "data": self._format(rec)}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[Refund] DB 不可用，回退 JSON：{e}")
        self._load()
        return await self._execute_json(order_id, refund_id)

    async def _fetch_order(self, order_id: str) -> dict[str, Any] | None:
        try:
            from ..database.db import get_session_factory
            from ..database.repositories_async import OrderRepository as AsyncRepo

            async with get_session_factory()() as s:
                return await AsyncRepo(s).get_by_id(order_id)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Refund] DB 不可用，JSON 回退查归属：{e}")
            p = self._data_dir / "orders" / f"{order_id}.json"
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    return None
            return None

    async def _execute_json(self, order_id: str, refund_id: str) -> dict[str, Any]:
        if order_id:
            refund_id = self._by_order.get(order_id, "")
            if not refund_id:
                return {"success": True, "data": None, "message": f"未找到订单 {order_id} 的退款记录"}
        if refund_id:
            record = self._refunds.get(refund_id)
            if not record:
                return {"success": True, "data": None, "message": f"未找到退款单号 {refund_id}"}
            return {"success": True, "data": self._format(record)}
        return {"success": False, "error": "请提供订单号或退款单号"}

    def _format(self, record: dict[str, Any]) -> dict[str, Any]:
        stages = record.get("stages", [])
        current_stage = next((s["stage"] for s in stages if not s.get("completed")), None)
        result = dict(record)
        result["current_stage"] = current_stage
        result["progress"] = f"{sum(1 for s in stages if s.get('completed'))}/{len(stages)} 阶段完成"
        return result
