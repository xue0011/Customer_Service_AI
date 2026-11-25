"""数据层：异步引擎 + ORM 模型 + 仓储。

P0 起使用 PostgreSQL（生产）/ SQLite（测试）替代 JSON 文件与 MySQL。
旧 connection.py / repository.py 保留为 deprecated（legacy 模块仍引用）。
"""

from .db import (
    dispose,
    get_engine,
    get_session,
    get_session_factory,
    init_db,
)
from .models import (
    AgentTrace,
    ApprovalTask,
    AuditLog,
    Base,
    IdempotencyKey,
    Logistics,
    Message,
    Order,
    OrderItem,
    Product,
    ProductVariant,
    Refund,
    RefundRequest,
    Session,
    ToolCallLog,
    User,
)
from .repositories_async import (
    ApprovalRepository,
    AuditRepository,
    IdempotencyRepository,
    LogisticsRepository,
    ProductRepository,
    RefundRepository,
    RefundRequestRepository,
    SessionRepository,
    ToolCallLogRepository,
    UserRepository,
)
from .repositories_async import (
    OrderRepository as AsyncOrderRepository,
)

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
    "get_engine",
    "get_session",
    "get_session_factory",
    "init_db",
    "dispose",
    "UserRepository",
    "AsyncOrderRepository",
    "RefundRequestRepository",
    "ApprovalRepository",
    "AuditRepository",
    "ToolCallLogRepository",
    "IdempotencyRepository",
    "ProductRepository",
    "LogisticsRepository",
    "RefundRepository",
    "SessionRepository",
]
