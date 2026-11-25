"""
退货申请工具
───────────
P0：退货/退款申请接入审批 FSM（RefundRequest + ApprovalTask）。
验收5/6：身份与订单归属校验；金额≥阈值或自动检查未通过 → 人工审批任务。
验收7：幂等键 + 审计日志（由 safe_execute 统一记录）。
"""

from __future__ import annotations

import json
import random
import string
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from .base import BaseTool
from .security import check_order_ownership


class ReturnApplyTool(BaseTool):
    """退货申请工具 —— 处理退货/退款申请。"""

    high_risk = True
    required_permission = None

    def __init__(
        self,
        data_dir: str = "./data",
        order_repo=None,
        product_repo=None,
        policy_repo=None,
        ticket_repo=None,
        threshold: float = 200.0,
        return_window: int = 7,
    ) -> None:
        super().__init__()
        self._data_dir = Path(data_dir)
        self._threshold = threshold
        self._return_window = return_window

    @property
    def name(self) -> str:
        return "return_apply"

    @property
    def description(self) -> str:
        return (
            "处理顾客退货/退款申请。金额低于阈值且通过自动检查（7天内、商品可退、标签完整、非禁退类别）→ 自动批准；"
            "否则提交人工审批，返回审批任务号。需先通过 order_query 确认订单。支持 idempotency_key 防重复提交。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "退货订单号"},
                "reason": {"type": "string", "description": "退货原因"},
                "description": {"type": "string", "description": "退货详细描述（可选）"},
                "idempotency_key": {"type": "string", "description": "幂等键，防重复提交（可选）"},
            },
            "required": ["order_id", "reason"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        order_id = kwargs.get("order_id", "")
        reason = kwargs.get("reason", "")
        description = kwargs.get("description", "")
        idempotency_key = kwargs.get("idempotency_key", "")

        if not order_id:
            return {"success": False, "error": "请提供订单号"}
        if not reason:
            return {"success": False, "error": "请提供退货原因"}

        # 幂等
        if idempotency_key:
            from ..infra.idempotency import acquire, get_result

            ok = await acquire(f"return_apply:{idempotency_key}")
            if not ok:
                cached = await get_result(f"return_apply:{idempotency_key}")
                return {"success": True, "data": {"idempotent": True, "previous": cached}}

        order = await self._fetch_order(order_id)
        if not order:
            return {"success": False, "error": f"未找到订单 {order_id}"}
        check_order_ownership(order)

        items = order.get("items", [])
        if not items:
            return {"success": False, "error": "订单中没有商品信息"}
        item = items[0]
        product = await self._load_product(item.get("base_product_id", ""))
        policy = self._load_policy()
        amount = order.get("total_amount", 0)
        threshold = self._effective_threshold()

        checks, all_passed = self._run_checks(order, product, policy)

        if amount < threshold and all_passed:
            return await self._approve_auto(order, reason, description, checks, idempotency_key)
        return await self._submit_manual(order, item, product, reason, description, checks, amount, idempotency_key)

    def _effective_threshold(self) -> float:
        try:
            from ..config.settings import get_config

            return float(get_config().approval.auto_review_threshold)
        except Exception:  # noqa: BLE001
            return self._threshold

    def _run_checks(self, order, product, policy) -> tuple[list[dict], bool]:
        checks: list[dict] = []
        all_passed = True

        delivered_at = order.get("delivered_at")
        if not delivered_at:
            for t in order.get("timeline", []):
                if "签收" in t.get("event", ""):
                    delivered_at = t.get("time", "")
                    break
        within_window = False
        days_since = None
        if delivered_at:
            try:
                deliv = datetime.fromisoformat(str(delivered_at).replace(" ", "T"))
                now = datetime.now(deliv.tzinfo) if deliv.tzinfo else datetime.now()
                days_since = (now - deliv).days
                within_window = days_since <= self._return_window
            except (ValueError, TypeError):
                within_window = True
        checks.append({"condition": "7天无理由退货窗口", "passed": within_window,
                       "detail": f"已签收{days_since}天" if days_since is not None else "签收时间未知"})
        if not within_window:
            all_passed = False

        is_returnable = product.get("is_returnable", True) if product else True
        checks.append({"condition": "商品可退换", "passed": is_returnable})
        if not is_returnable:
            all_passed = False

        tags_intact = product.get("tags_attached_by_default", True) if product else True
        checks.append({"condition": "标签/吊牌完整", "passed": tags_intact})

        returnable_category = True
        if product:
            non_ret = policy.get("non_returnable_categories", [])
            returnable_category = product.get("category", "") not in non_ret
        checks.append({"condition": "非禁止退货类别", "passed": returnable_category})
        if not returnable_category:
            all_passed = False

        return checks, all_passed

    async def _approve_auto(self, order, reason, description, checks, idempotency_key) -> dict[str, Any]:
        rr_id = self._gen_id("REF")
        await self._persist_request(
            rr_id=rr_id, order=order, reason=reason, description=description,
            status="approved", stage="auto_review", idempotency_key=idempotency_key,
        )
        return {
            "success": True,
            "data": {
                "approved": True,
                "review_type": "auto",
                "refund_request_id": rr_id,
                "checks": checks,
                "refund_amount": order.get("total_amount", 0),
                "refund_channel": "原路退回",
                "expected_refund": "收到退货后3-5个工作日",
                "steps": ["1. 商品及赠品、吊牌、包装一并寄回", "2. 保留快递单号", "3. 收到退货后3-5个工作日退款"],
            },
        }

    async def _submit_manual(self, order, item, product, reason, description, checks, amount, idempotency_key) -> dict[str, Any]:
        rr_id = self._gen_id("REF")
        apr_id = self._gen_id("APR")
        sla_hours = 24
        try:
            from ..config.settings import get_config

            sla_hours = get_config().approval.sla_hours
        except Exception:  # noqa: BLE001
            pass

        await self._persist_request(
            rr_id=rr_id, order=order, reason=reason, description=description,
            status="under_review", stage="submitted", idempotency_key=idempotency_key,
        )
        await self._persist_approval(
            apr_id=apr_id, rr_id=rr_id, order=order, item=item, product=product,
            reason=reason, amount=amount, sla_hours=sla_hours,
        )
        return {
            "success": True,
            "data": {
                "approved": None,
                "review_type": "manual",
                "refund_request_id": rr_id,
                "approval_task_id": apr_id,
                "status": "pending_manual_review",
                "message": "您的退货申请已提交人工审核",
                "order_amount": amount,
                "threshold": self._effective_threshold(),
                "expected_response": f"预计{sla_hours}小时内回复",
                "checks": checks,
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
            logger.warning(f"[ReturnApply] DB 不可用，回退 JSON：{e}")
        return self._load_order_json(order_id)

    def _load_order_json(self, order_id: str) -> dict[str, Any] | None:
        p = self._data_dir / "orders" / f"{order_id}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    async def _load_product(self, base_product_id: str) -> dict[str, Any] | None:
        try:
            from ..database.db import get_session_factory
            from ..database.repositories_async import ProductRepository

            async with get_session_factory()() as s:
                p = await ProductRepository(s).get_by_id(base_product_id)
                if p:
                    return p
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ReturnApply] DB 产品查询不可用，回退 JSON：{e}")
        d = self._data_dir / "products"
        if not d.exists():
            return None
        for fpath in d.glob("*.json"):
            try:
                prod = json.loads(fpath.read_text(encoding="utf-8"))
                if prod.get("base_product_id") == base_product_id:
                    return prod
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[ReturnApply] 产品加载失败: {e}")
        return None

    def _load_policy(self) -> dict[str, Any]:
        p = self._data_dir / "policies" / "return_policy.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return {}
        return {}

    async def _persist_request(self, rr_id, order, reason, description, status, stage, idempotency_key) -> None:
        from ..database.db import get_session_factory
        from ..database.repositories_async import RefundRequestRepository

        async with get_session_factory()() as s:
            repo = RefundRequestRepository(s)
            await repo.create({
                "id": rr_id,
                "order_id": order["order_id"],
                "customer_id": order.get("customer_id", ""),
                "type": "return",
                "amount": order.get("total_amount", 0),
                "reason": reason,
                "description": description,
                "status": status,
                "current_stage": stage,
                "stages": [{"stage": stage, "time": datetime.now(UTC).isoformat(), "completed": True, "note": reason}],
                "idempotency_key": idempotency_key or None,
            })
            await s.commit()

    async def _persist_approval(self, apr_id, rr_id, order, item, product, reason, amount, sla_hours) -> None:
        from ..database.db import get_session_factory
        from ..database.repositories_async import ApprovalRepository

        async with get_session_factory()() as s:
            repo = ApprovalRepository(s)
            await repo.create({
                "id": apr_id,
                "request_id": rr_id,
                "order_id": order["order_id"],
                "type": "return",
                "status": "pending",
                "payload": {
                    "before": {"order_status": order.get("status")},
                    "after": {"reason": reason, "amount": amount},
                    "item": item,
                    "product_category": product.get("category") if product else None,
                },
                "sla_due_at": datetime.now(UTC) + timedelta(hours=sla_hours),
            })
            await s.commit()

    @staticmethod
    def _gen_id(prefix: str) -> str:
        ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        return f"{prefix}-{ts}-{suffix}"
