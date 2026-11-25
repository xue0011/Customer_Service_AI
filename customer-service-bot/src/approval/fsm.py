"""状态机：退款/退货/改地址流程（验收6）。

设计选择：显式状态转换表 + transition 校验，避免非法跳转（如 approved→submitted）。
替代方案：transitions 库（功能全但加依赖）——P1 自实现轻量 FSM。

退款/退货 FSM：
  submitted → under_review → approved → return_received → refunded → closed
                └→ rejected / escalated（任意阶段可拒绝/升级）

改地址 FSM（走 ApprovalTask type=address_change）：
  requested → approved → applied → closed
"""

from __future__ import annotations

REFUND_TRANSITIONS: dict[str, list[str]] = {
    "submitted": ["under_review", "rejected"],
    "under_review": ["approved", "rejected", "escalated"],
    "escalated": ["approved", "rejected"],
    "approved": ["return_received", "rejected"],
    "return_received": ["refunded"],
    "refunded": ["closed"],
    "rejected": ["closed"],
    "closed": [],
}

ADDRESS_TRANSITIONS: dict[str, list[str]] = {
    "requested": ["approved", "rejected"],
    "approved": ["applied"],
    "applied": ["closed"],
    "rejected": ["closed"],
    "closed": [],
}


class WorkflowError(ValueError):
    """非法状态转换。"""


def assert_transition(transitions: dict[str, list[str]], frm: str, to: str) -> None:
    if to not in transitions.get(frm, []):
        raise WorkflowError(f"非法状态转换: {frm} → {to}")


def can_transition(transitions: dict[str, list[str]], frm: str, to: str) -> bool:
    return to in transitions.get(frm, [])


def is_terminal(state: str, transitions: dict[str, list[str]]) -> bool:
    return not transitions.get(state)


def next_states(state: str, transitions: dict[str, list[str]]) -> list[str]:
    return list(transitions.get(state, []))
