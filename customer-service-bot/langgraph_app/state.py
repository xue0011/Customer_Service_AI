"""图状态定义：LangGraph 的节点之间只通过这份 TypedDict 通信。"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages

Intent = Literal["presales", "aftersales", "device", "chitchat"]


class AgentState(TypedDict, total=False):
    # 对话消息由 add_messages reducer 合并（含工具消息）
    messages: Annotated[list, add_messages]

    # 请求上下文
    customer_id: str
    thread_id: str
    text: str

    # 路由结果
    intent: Intent
    confidence: float
    route_reason: str
    skill: str

    # 输入护栏
    blocked: bool
    block_reason: str

    # 人工审批（interrupt / Command(resume=...)）
    requires_approval: bool
    approval_reason: str
    approved: bool
    pending_action: dict[str, Any]

    # 观测
    citations: list[str]
    tool_calls: list[str]
    escalated: bool
    reply: str
