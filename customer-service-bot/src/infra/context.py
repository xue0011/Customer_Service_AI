"""请求级上下文（基于 contextvars）。

Runner/工具层通过本模块获取当前调用者身份（Actor），用于：
  - 订单/退款归属校验（IDOR 防护）
  - 审计日志记录 who
  - 工具调用日志关联 actor
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass


@dataclass
class Actor:
    """当前请求的调用者身份。"""

    user_id: str
    role: str = "customer"               # customer / agent / lead / admin
    customer_id: str | None = None       # 顾客绑定的外部 id
    display_name: str = ""
    is_authenticated: bool = True

    # 便捷权限
    def is_staff(self) -> bool:
        return self.role in ("agent", "lead", "admin")

    def is_admin(self) -> bool:
        return self.role == "admin"


_actor_var: contextvars.ContextVar[Actor | None] = contextvars.ContextVar("actor", default=None)
_session_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("session_id", default=None)
_trace_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)
_corr_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)


def set_actor(actor: Actor | None) -> contextvars.Token[Actor | None]:
    return _actor_var.set(actor)


def get_actor() -> Actor | None:
    return _actor_var.get()


def require_actor() -> Actor:
    a = _actor_var.get()
    if a is None:
        raise PermissionError("无调用者上下文（actor 未设置），拒绝执行需鉴权的操作。")
    return a


def set_session_id(sid: str | None) -> contextvars.Token[str | None]:
    return _session_var.set(sid)


def get_session_id() -> str | None:
    return _session_var.get()


def set_trace_id(tid: str | None) -> contextvars.Token[str | None]:
    return _trace_var.set(tid)


def get_trace_id() -> str | None:
    return _trace_var.get()


def set_correlation_id(cid: str | None) -> contextvars.Token[str | None]:
    return _corr_var.set(cid)


def get_correlation_id() -> str | None:
    return _corr_var.get()
