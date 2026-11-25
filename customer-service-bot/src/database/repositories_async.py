"""
异步仓储层 —— 业务表读写。

返回的字典刻意与原 JSON 文件结构对齐，便于工具层无感切换。
所有写操作在调用方的事务上下文中执行。
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    ApprovalTask,
    AuditLog,
    IdempotencyKey,
    Logistics,
    Message,
    Order,
    Product,
    ProductVariant,
    Refund,
    RefundRequest,
    Session,
    ToolCallLog,
    User,
)


def _dt(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _coerce_dt(v: Any) -> datetime | None:
    """把字符串/None/datetime 统一为 datetime | None（写入 DateTime 列用）。"""
    if v is None or isinstance(v, datetime):
        return v
    if isinstance(v, str):
        s = v.strip().replace(" ", "T")
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            try:
                return datetime.strptime(v.strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    return None


# ─── 用户 ──────────────────────────────────────────────────────────────────

class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: str) -> User | None:
        r = await self.session.get(User, user_id)
        return r

    async def get_by_username(self, username: str) -> User | None:
        r = await self.session.execute(select(User).where(User.username == username))
        return r.scalar_one_or_none()

    async def get_by_customer_id(self, customer_id: str) -> User | None:
        r = await self.session.execute(select(User).where(User.customer_id == customer_id))
        return r.scalar_one_or_none()

    async def create_customer(self, customer_id: str, name: str = "") -> User:
        """幂等创建顾客（按 customer_id）。"""
        existing = await self.get_by_customer_id(customer_id)
        if existing:
            return existing
        user = User(
            username=None,
            display_name=name or customer_id,
            role="customer",
            customer_id=customer_id,
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def create_user(
        self,
        username: str,
        password_hash: str,
        role: str = "agent",
        display_name: str = "",
    ) -> User:
        user = User(
            username=username,
            display_name=display_name or username,
            password_hash=password_hash,
            role=role,
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def list_by_role(self, role: str) -> list[User]:
        r = await self.session.execute(select(User).where(User.role == role, User.is_active.is_(True)))
        return list(r.scalars().all())


# ─── 订单 ──────────────────────────────────────────────────────────────────

class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, order_id: str) -> dict[str, Any] | None:
        r = await self.session.get(Order, order_id)
        if not r:
            return None
        return {
            "order_id": r.order_id,
            "platform": r.platform,
            "customer_id": r.customer_id,
            "customer_name": r.customer_name,
            "customer_phone": r.customer_phone,
            "status": r.status,
            "status_display": r.status_display,
            "total_amount": r.total_amount,
            "shipping_fee": r.shipping_fee,
            "discount": r.discount,
            "payment_method": r.payment_method,
            "shipping_address": r.shipping_address or {},
            "timeline": r.timeline or [],
            "items": r.items or [],
            "created_at": _dt(r.created_at),
            "paid_at": _dt(r.paid_at),
            "shipped_at": _dt(r.shipped_at),
            "delivered_at": _dt(r.delivered_at),
            "version": r.version,
        }

    async def get_by_customer(self, customer_id: str) -> list[dict[str, Any]]:
        r = await self.session.execute(
            select(Order).where(Order.customer_id == customer_id).order_by(Order.created_at.desc())
        )
        rows = r.scalars().all()
        return [await self._to_dict(o) for o in rows]

    async def get_by_phone(self, phone: str) -> list[dict[str, Any]]:
        r = await self.session.execute(select(Order).where(Order.customer_phone == phone))
        rows = r.scalars().all()
        return [await self._to_dict(o) for o in rows]

    @staticmethod
    async def _to_dict(o: Order) -> dict[str, Any]:
        return {
            "order_id": o.order_id,
            "platform": o.platform,
            "customer_id": o.customer_id,
            "customer_name": o.customer_name,
            "customer_phone": o.customer_phone,
            "status": o.status,
            "status_display": o.status_display,
            "total_amount": o.total_amount,
            "shipping_fee": o.shipping_fee,
            "discount": o.discount,
            "payment_method": o.payment_method,
            "shipping_address": o.shipping_address or {},
            "timeline": o.timeline or [],
            "items": o.items or [],
            "created_at": _dt(o.created_at),
            "paid_at": _dt(o.paid_at),
            "shipped_at": _dt(o.shipped_at),
            "delivered_at": _dt(o.delivered_at),
            "version": o.version,
        }

    async def save(self, order_dict: dict[str, Any]) -> None:
        """upsert 订单（带乐观锁，时间字段自动强转）。"""
        oid = order_dict["order_id"]

        # datetime 列强转（JSON 里可能是字符串）
        for k in ("created_at", "paid_at", "shipped_at", "delivered_at"):
            if k in order_dict:
                order_dict[k] = _coerce_dt(order_dict[k])
        existing = await self.session.get(Order, oid)
        if existing is None:
            obj = Order(
                order_id=oid,
                platform=order_dict.get("platform", ""),
                customer_id=order_dict.get("customer_id", ""),
                customer_name=order_dict.get("customer_name", ""),
                customer_phone=order_dict.get("customer_phone"),
                status=order_dict.get("status", ""),
                status_display=order_dict.get("status_display"),
                total_amount=order_dict.get("total_amount", 0),
                shipping_fee=order_dict.get("shipping_fee", 0),
                discount=order_dict.get("discount", 0),
                payment_method=order_dict.get("payment_method"),
                shipping_address=order_dict.get("shipping_address"),
                timeline=order_dict.get("timeline"),
                items=order_dict.get("items"),
                version=1,
            )
            self.session.add(obj)
        else:
            # 乐观锁：检查 version
            expected = order_dict.get("version", existing.version)
            if existing.version != expected:
                raise RuntimeError(
                    f"order {oid} 版本冲突: 期望 {expected}, 实际 {existing.version}"
                )
            for k, v in order_dict.items():
                if k in ("order_id", "version"):
                    continue
                if hasattr(existing, k):
                    setattr(existing, k, v)
            existing.version = (existing.version or 1) + 1
        await self.session.flush()


# ─── 退款/退货申请 ─────────────────────────────────────────────────────────

class RefundRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, data: dict[str, Any]) -> RefundRequest:
        obj = RefundRequest(**{k: v for k, v in data.items() if hasattr(RefundRequest, k) or k == "stages"})
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get(self, request_id: str) -> dict[str, Any] | None:
        r = await self.session.get(RefundRequest, request_id)
        if not r:
            return None
        return {
            "id": r.id,
            "order_id": r.order_id,
            "customer_id": r.customer_id,
            "type": r.type,
            "amount": r.amount,
            "reason": r.reason,
            "description": r.description,
            "status": r.status,
            "current_stage": r.current_stage,
            "stages": r.stages or [],
            "assigned_to": r.assigned_to,
            "sla_due_at": _dt(r.sla_due_at),
            "idempotency_key": r.idempotency_key,
            "created_at": _dt(r.created_at),
            "updated_at": _dt(r.updated_at),
        }

    async def list_by_customer(self, customer_id: str) -> list[dict[str, Any]]:
        r = await self.session.execute(
            select(RefundRequest).where(RefundRequest.customer_id == customer_id).order_by(
                RefundRequest.created_at.desc()
            )
        )
        return [
            {
                "id": o.id,
                "order_id": o.order_id,
                "type": o.type,
                "amount": o.amount,
                "status": o.status,
                "created_at": _dt(o.created_at),
            }
            for o in r.scalars().all()
        ]

    async def update_status(
        self,
        request_id: str,
        status: str,
        stage: str | None = None,
        note: str = "",
    ) -> RefundRequest | None:
        r = await self.session.get(RefundRequest, request_id)
        if not r:
            return None
        r.status = status
        if stage:
            r.current_stage = stage
        stages = r.stages or []
        stages.append({"stage": stage or status, "time": datetime.now(UTC).isoformat(), "completed": True, "note": note})
        r.stages = stages
        await self.session.flush()
        return r

    async def transition(
        self, request_id: str, to: str, stage: str | None = None, note: str = ""
    ) -> RefundRequest | None:
        """带 FSM 校验的状态转换（验收6）。"""
        from ..approval.fsm import REFUND_TRANSITIONS, assert_transition

        r = await self.session.get(RefundRequest, request_id)
        if not r:
            return None
        assert_transition(REFUND_TRANSITIONS, r.status, to)
        return await self.update_status(request_id, to, stage, note)


# ─── 审批 ──────────────────────────────────────────────────────────────────

class ApprovalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, data: dict[str, Any]) -> ApprovalTask:
        obj = ApprovalTask(**{k: v for k, v in data.items() if hasattr(ApprovalTask, k)})
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get(self, approval_id: str) -> ApprovalTask | None:
        return await self.session.get(ApprovalTask, approval_id)

    async def list_pending(self, type_: str | None = None) -> list[ApprovalTask]:
        stmt = select(ApprovalTask).where(ApprovalTask.status == "pending")
        if type_:
            stmt = stmt.where(ApprovalTask.type == type_)
        stmt = stmt.order_by(ApprovalTask.created_at.asc())
        r = await self.session.execute(stmt)
        return list(r.scalars().all())

    async def resolve(
        self,
        approval_id: str,
        status: str,
        approver_id: str,
        note: str = "",
    ) -> ApprovalTask | None:
        a = await self.session.get(ApprovalTask, approval_id)
        if not a:
            return None
        a.status = status  # approved/rejected/escalated
        a.approver_id = approver_id
        a.resolution_note = note
        a.resolved_at = datetime.now(UTC)
        await self.session.flush()
        return a


# ─── 审计 & 工具调用日志 ────────────────────────────────────────────────────

class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        actor_id: str | None,
        actor_role: str | None,
        action: str,
        resource: str = "",
        before: dict | None = None,
        after: dict | None = None,
        correlation_id: str | None = None,
    ) -> AuditLog:
        log = AuditLog(
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            resource=resource,
            before=before,
            after=after,
            correlation_id=correlation_id,
        )
        self.session.add(log)
        await self.session.flush()
        return log


class ToolCallLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, data: dict[str, Any]) -> ToolCallLog:
        log = ToolCallLog(
            session_id=data.get("session_id"),
            trace_id=data.get("trace_id"),
            tool_name=data["tool_name"],
            arguments=data.get("arguments", {}),
            result=data.get("result"),
            success=data.get("success", True),
            error=data.get("error"),
            duration_ms=data.get("duration_ms", 0.0),
            actor_id=data.get("actor_id"),
            actor_role=data.get("actor_role"),
        )
        self.session.add(log)
        await self.session.flush()
        return log


# ─── 幂等（DB 兜底，主用 Redis）──────────────────────────────────────────

class IdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def acquire(self, key: str, scope: str, actor_id: str | None, ttl_seconds: int = 86400) -> bool:
        """尝试占用幂等键（用独立事务，避免回滚污染业务会话）。

        返回 True 表示获得，False 表示已存在（重复提交）。主路径应使用 Redis
        （infra.idempotency）；本方法为持久兜底。
        """
        from sqlalchemy import insert
        from sqlalchemy.exc import IntegrityError

        from .db import get_session_factory
        factory = get_session_factory()
        async with factory() as s:
            try:
                await s.execute(
                    insert(IdempotencyKey).values(
                        key=key,
                        scope=scope,
                        actor_id=actor_id,
                        status="pending",
                        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
                    )
                )
                await s.commit()
                return True
            except IntegrityError:
                await s.rollback()
                return False

    async def set_result(self, key: str, status: str, result: dict | None) -> None:
        await self.session.execute(
            update(IdempotencyKey).where(IdempotencyKey.key == key).values(status=status, result=result)
        )
        await self.session.flush()

    async def get(self, key: str) -> dict[str, Any] | None:
        from sqlalchemy import delete
        now = datetime.now(UTC)
        # 清理过期
        await self.session.execute(delete(IdempotencyKey).where(IdempotencyKey.expires_at < now))
        r = await self.session.execute(select(IdempotencyKey).where(IdempotencyKey.key == key))
        row = r.scalar_one_or_none()
        if not row:
            return None
        return {"status": row.status, "result": row.result}

    @staticmethod
    def hash_key(scope: str, actor_id: str | None, key: str) -> str:
        raw = f"{scope}:{actor_id or ''}:{key}"
        return hashlib.sha256(raw.encode()).hexdigest()[:64]


# ─── 商品 ──────────────────────────────────────────────────────────────────

class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, base_product_id: str) -> dict[str, Any] | None:
        p = await self.session.get(Product, base_product_id)
        if not p:
            return None
        return {
            "base_product_id": p.base_product_id,
            "name": p.name,
            "category": p.category,
            "subcategory": p.subcategory,
            "brand": p.brand,
            "description": p.description,
            "specs": p.specs or {},
            "available_sizes": p.available_sizes or [],
            "available_colors": p.available_colors or [],
            "images": p.images or [],
            "variants": p.variants or [],
            "is_returnable": p.is_returnable,
            "returnable_category": p.returnable_category,
            "tags_attached_by_default": p.tags_attached_by_default,
            "returnable_condition": p.returnable_condition,
        }

    async def save(self, product: dict[str, Any]) -> None:
        """upsert 商品 + 同步 variants（不覆盖已扣减的库存）。"""
        pid = product["base_product_id"]
        existing = await self.session.get(Product, pid)
        if existing is None:
            obj = Product(
                base_product_id=pid,
                name=product.get("name", ""),
                category=product.get("category"),
                subcategory=product.get("subcategory"),
                brand=product.get("brand"),
                description=product.get("description"),
                specs=product.get("specs"),
                available_sizes=product.get("available_sizes"),
                available_colors=product.get("available_colors"),
                images=product.get("images"),
                variants=product.get("variants"),
                is_returnable=product.get("is_returnable", True),
                returnable_category=product.get("returnable_category"),
                tags_attached_by_default=product.get("tags_attached_by_default", True),
                returnable_condition=product.get("returnable_condition"),
            )
            self.session.add(obj)
        else:
            for k, v in product.items():
                if k == "base_product_id":
                    continue
                if hasattr(existing, k) and k != "variants":
                    setattr(existing, k, v)
            existing.variants = product.get("variants", existing.variants)
        for v in product.get("variants", []):
            sku = v.get("sku")
            if not sku:
                continue
            r = await self.session.execute(select(ProductVariant).where(ProductVariant.sku == sku))
            pv = r.scalar_one_or_none()
            if pv is None:
                self.session.add(
                    ProductVariant(
                        base_product_id=pid, sku=sku, color=v.get("color"),
                        size=v.get("size"), price=v.get("price"), stock=v.get("stock", 0),
                    )
                )
            else:
                pv.price = v.get("price", pv.price)
                pv.color = v.get("color", pv.color)
                pv.size = v.get("size", pv.size)
                # 不覆盖 stock，保留扣减后的实际库存
        await self.session.flush()

    async def decrement_stock(self, sku: str, qty: int = 1) -> bool:
        r = await self.session.execute(select(ProductVariant).where(ProductVariant.sku == sku))
        pv = r.scalar_one_or_none()
        if pv is None or pv.stock < qty:
            return False
        pv.stock -= qty
        await self.session.flush()
        return True

    async def increment_stock(self, sku: str, qty: int = 1) -> bool:
        r = await self.session.execute(select(ProductVariant).where(ProductVariant.sku == sku))
        pv = r.scalar_one_or_none()
        if pv is None:
            return False
        pv.stock += qty
        await self.session.flush()
        return True


# ─── 物流 ──────────────────────────────────────────────────────────────────

class LogisticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_tracking(self, tracking_no: str) -> dict[str, Any] | None:
        log = await self.session.get(Logistics, tracking_no)
        return self._to_dict(log) if log else None

    async def get_by_order(self, order_id: str) -> dict[str, Any] | None:
        r = await self.session.execute(select(Logistics).where(Logistics.order_id == order_id))
        log = r.scalar_one_or_none()
        return self._to_dict(log) if log else None

    @staticmethod
    def _to_dict(log: Logistics) -> dict[str, Any]:
        return {
            "tracking_no": log.tracking_no, "order_id": log.order_id, "company": log.company,
            "company_code": log.company_code, "status": log.status,
            "current_location": log.current_location,
            "estimated_delivery": _dt(log.estimated_delivery),
            "origin": log.origin, "destination": log.destination,
            "tracking_history": log.tracking_history or [],
            "signed_by": log.signed_by, "signed_time": _dt(log.signed_time),
        }


# ─── 退款记录 ──────────────────────────────────────────────────────────────

class RefundRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, refund_id: str) -> dict[str, Any] | None:
        r = await self.session.get(Refund, refund_id)
        return self._to_dict(r) if r else None

    async def get_by_order(self, order_id: str) -> dict[str, Any] | None:
        r = await self.session.execute(select(Refund).where(Refund.order_id == order_id))
        x = r.scalar_one_or_none()
        return self._to_dict(x) if x else None

    @staticmethod
    def _to_dict(r: Refund) -> dict[str, Any]:
        return {
            "refund_id": r.refund_id, "order_id": r.order_id, "status": r.status,
            "status_display": r.status_display, "amount": r.amount, "reason": r.reason,
            "type": r.type, "applied_at": _dt(r.applied_at),
            "stages": r.stages or [], "refund_channel": r.refund_channel,
            "expected_completion": _dt(r.expected_completion),
        }


# ─── 会话 / 消息（替代进程内内存）──────────────────────────────────────────

class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(
        self, session_id: str, customer_id: str | None = None, channel: str = "web"
    ) -> Session:
        s = await self.session.get(Session, session_id)
        if s is None:
            s = Session(id=session_id, customer_id=customer_id, channel=channel, status="open")
            self.session.add(s)
            await self.session.flush()
        return s

    async def append_message(
        self, session_id: str, role: str, content: str,
        intent: str | None = None, agent: str | None = None, metadata: dict | None = None,
    ) -> Message:
        m = Message(
            session_id=session_id, role=role, content=content, intent=intent,
            agent=agent, metadata_=metadata or {},
        )
        self.session.add(m)
        await self.session.flush()
        return m

    async def get_history(self, session_id: str, limit: int = 20) -> list[dict[str, str]]:
        r = await self.session.execute(
            select(Message).where(Message.session_id == session_id)
            .order_by(Message.created_at.desc()).limit(limit)
        )
        rows = list(reversed(r.scalars().all()))
        return [{"role": m.role, "content": m.content} for m in rows]
