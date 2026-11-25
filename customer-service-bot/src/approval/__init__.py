"""审批与状态机：退款/退货/改地址流程。"""

from .fsm import (
    ADDRESS_TRANSITIONS,
    REFUND_TRANSITIONS,
    WorkflowError,
    assert_transition,
    can_transition,
    is_terminal,
    next_states,
)

__all__ = [
    "REFUND_TRANSITIONS",
    "ADDRESS_TRANSITIONS",
    "WorkflowError",
    "assert_transition",
    "can_transition",
    "is_terminal",
    "next_states",
]
