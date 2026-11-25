"""
SQLAlchemy ORM 模型 —— 企业级核心表。

覆盖验收：用户、会话、消息、订单、退款申请、审批任务、Agent Trace、
工具调用日志、审计日志、幂等键。

设计原则：
  - 主键用 String(36) UUID（兼容 PG / SQLite 测试）
  - 枚举用 String 存储而非 SQL Enum（跨方言兼容）
  - JSON 列用 sqlalchemy.JSON（PG→json，SQLite→text）
  - 不设 ORM relationship（避免 async 懒加载问题），按需 join
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    pass


# ─── 认证授权 ──────────────────────────────────────────────────────────────

class User(Base):
    """用户：顾客 / 坐席 / 主管 / 管理员。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 顾客可空
    role: Mapped[str] = mapped_column(String(16), default="customer", index=True)  # customer/agent/lead/admin
    customer_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)  # 绑定外部顾客 id
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class RefreshToken(Base):
    """JWT 刷新令牌（服务端可吊销）。"""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 hex
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ─── 会话与消息 ────────────────────────────────────────────────────────────

class Session(Base):
    """会话（对话线程）。"""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # thread_id
    customer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    assigned_agent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    channel: Mapped[str] = mapped_column(String(32), default="web")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open/handoff/closed
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Message(Base):
    """对话消息。"""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user/assistant/system/tool
    content: Mapped[str] = mapped_column(Text, default="")
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tool_calls: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


# ─── 订单 ──────────────────────────────────────────────────────────────────

class Order(Base):
    """订单。customer_id 为外部顾客 id（与 users.customer_id 对齐做归属校验）。"""

    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), default="")
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_name: Mapped[str] = mapped_column(String(100), default="")
    customer_phone: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    status_display: Mapped[str | None] = mapped_column(String(20), nullable=True)
    total_amount: Mapped[float] = mapped_column(Float, default=0)
    shipping_fee: Mapped[float] = mapped_column(Float, default=0)
    discount: Mapped[float] = mapped_column(Float, default=0)
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    shipping_address: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    timeline: Mapped[list | None] = mapped_column(JSON, nullable=True)
    items: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 冗余快照便于查询
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)  # 乐观锁


class OrderItem(Base):
    """订单明细（规范化）。"""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(50), ForeignKey("orders.order_id", ondelete="CASCADE"), index=True)
    sku: Mapped[str | None] = mapped_column(String(50), nullable=True)
    base_product_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    color: Mapped[str | None] = mapped_column(String(30), nullable=True)
    size: Mapped[str | None] = mapped_column(String(10), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)


# ─── 退款 / 退货申请 ───────────────────────────────────────────────────────

class RefundRequest(Base):
    """退款/退货申请 FSM。

    状态机：submitted → under_review → approved → return_received → refunded → closed
                    └→ rejected（任何阶段可拒绝）
    """

    __tablename__ = "refund_requests"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # REF-...
    order_id: Mapped[str] = mapped_column(String(50), ForeignKey("orders.order_id", ondelete="SET NULL"), index=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(16), default="return")  # refund/return
    amount: Mapped[float] = mapped_column(Float, default=0)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="submitted", index=True)
    current_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stages: Mapped[list] = mapped_column(JSON, default=list)  # [{stage,time,completed,note}]
    assigned_to: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ApprovalTask(Base):
    """审批任务（高风险操作：退货/退款/改单）。"""

    __tablename__ = "approval_tasks"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # APR-...
    request_id: Mapped[str | None] = mapped_column(String(50), ForeignKey("refund_requests.id", ondelete="SET NULL"), nullable=True, index=True)
    order_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(20), default="refund")  # refund/modify_order/return
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending/approved/rejected/escalated
    assignee_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approver_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # {before, after, summary}
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ─── 可观测：Agent Trace 与工具调用日志 ────────────────────────────────────

class AgentTrace(Base):
    """Agent 执行轨迹。"""

    __tablename__ = "agent_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent: Mapped[str] = mapped_column(String(32))
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_in: Mapped[int] = mapped_column(Integer, default=0)
    token_out: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class ToolCallLog(Base):
    """工具调用日志（审计 + 可观测）。"""

    __tablename__ = "tool_call_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tool_name: Mapped[str] = mapped_column(String(64), index=True)
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


# ─── 审计日志 ──────────────────────────────────────────────────────────────

class AuditLog(Base):
    """不可篡改审计日志（append-only）。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    action: Mapped[str] = mapped_column(String(32), index=True)  # login/tool_call/approval/mutation/...
    resource: Mapped[str] = mapped_column(String(128), default="")
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


# ─── 幂等 ──────────────────────────────────────────────────────────────────

class IdempotencyKey(Base):
    """幂等键持久化（Redis 为主，DB 为持久兜底）。"""

    __tablename__ = "idempotency_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(32), default="default")  # return_apply/modify_order/...
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/done
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)


# ─── 商品 / 物流 / 退款记录 ─────────────────────────────────────────────────

class Product(Base):
    """商品。"""

    __tablename__ = "products"

    base_product_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    subcategory: Mapped[str | None] = mapped_column(String(50), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    specs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    available_sizes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    available_colors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    variants: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 冗余快照
    is_returnable: Mapped[bool] = mapped_column(Boolean, default=True)
    returnable_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tags_attached_by_default: Mapped[bool] = mapped_column(Boolean, default=True)
    returnable_condition: Mapped[str | None] = mapped_column(String(50), nullable=True)


class ProductVariant(Base):
    """商品规格（规范化，含库存）。"""

    __tablename__ = "product_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    base_product_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("products.base_product_id", ondelete="CASCADE"), index=True
    )
    sku: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    color: Mapped[str | None] = mapped_column(String(30), nullable=True)
    size: Mapped[str | None] = mapped_column(String(10), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stock: Mapped[int] = mapped_column(Integer, default=0)


class Logistics(Base):
    """物流记录。"""

    __tablename__ = "logistics"

    tracking_no: Mapped[str] = mapped_column(String(50), primary_key=True)
    order_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    company: Mapped[str | None] = mapped_column(String(50), nullable=True)
    company_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    current_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    estimated_delivery: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    origin: Mapped[str | None] = mapped_column(String(100), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tracking_history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    signed_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    signed_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Refund(Base):
    """退款记录（已发生的退款，区别于 RefundRequest 申请）。"""

    __tablename__ = "refunds"

    refund_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    order_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status_display: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    refund_channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expected_completion: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ─── RAG 文档与向量 ───────────────────────────────────────────────────────

class RAGDocument(Base):
    """RAG 文档（上传/解析/切分/向量化）。"""

    __tablename__ = "rag_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(255), default="", index=True)
    category: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    chunks_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="uploaded", index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class RAGEmbedding(Base):
    """文档分块向量。

    embedding 存 JSON list[float]（兼容 SQLite 测试与应用层 cosine）；
    生产可启用 pgvector Vector 列 + ANN 索引优化（见 MIGRATION）。
    """

    __tablename__ = "rag_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rag_documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    chunk_text: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


__all__ = [
    "Base",
    "User",
    "RefreshToken",
    "Session",
    "Message",
    "Order",
    "OrderItem",
    "Product",
    "ProductVariant",
    "Logistics",
    "Refund",
    "RefundRequest",
    "ApprovalTask",
    "AgentTrace",
    "ToolCallLog",
    "AuditLog",
    "IdempotencyKey",
    "RAGDocument",
    "RAGEmbedding",
]
