"""LangGraph 状态图装配。

    START → input_guard ──阻断──→ reject → END
                │
                └→ router ──低置信度──→ escalate → END
                      ├→ presales ─┐
                      ├→ aftersales├→ risk_gate ──需审批──→ approval ─┐
                      ├→ device    ┤                      （interrupt） │
                      └→ chitchat ─┘→ output_guard ←───────────────────┘
                                            │
                                           END
"""

from __future__ import annotations

import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .mcp_client import load_device_tools
from .nodes import (
    after_route,
    approval_node,
    chitchat_node,
    escalate_node,
    input_guard_node,
    make_agent_node,
    output_guard_node,
    reject_node,
    risk_gate_node,
    route_node,
)
from .state import AgentState

logger = logging.getLogger(__name__)


def build_graph(device_tools: list | None = None, checkpointer=None):
    graph = StateGraph(AgentState)

    graph.add_node("input_guard", input_guard_node)
    graph.add_node("reject", reject_node)
    graph.add_node("router", route_node)
    graph.add_node("escalate", escalate_node)
    graph.add_node("presales", make_agent_node("presales"))
    graph.add_node("aftersales", make_agent_node("aftersales"))
    graph.add_node("device", make_agent_node("device", device_tools))
    graph.add_node("chitchat", chitchat_node)
    graph.add_node("risk_gate", risk_gate_node)
    graph.add_node("approval", approval_node)
    graph.add_node("output_guard", output_guard_node)

    graph.add_edge(START, "input_guard")
    graph.add_conditional_edges(
        "input_guard",
        lambda s: "reject" if s.get("blocked") else "router",
        {"reject": "reject", "router": "router"},
    )
    graph.add_conditional_edges(
        "router",
        after_route,
        {
            "escalate": "escalate",
            "presales": "presales",
            "aftersales": "aftersales",
            "device": "device",
            "chitchat": "chitchat",
        },
    )
    for node in ("presales", "aftersales", "device", "chitchat"):
        graph.add_edge(node, "risk_gate")

    graph.add_conditional_edges(
        "risk_gate",
        lambda s: "approval" if s.get("requires_approval") else "output_guard",
        {"approval": "approval", "output_guard": "output_guard"},
    )
    graph.add_edge("approval", "output_guard")
    graph.add_edge("output_guard", END)
    graph.add_edge("escalate", END)
    graph.add_edge("reject", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())


_graph = None
_device_tools: list = []


def get_device_tools() -> list:
    """已加载的 MCP 设备工具（未初始化时为空列表）。"""
    return _device_tools


async def get_graph():
    """进程内单例；首次调用时异步加载 MCP 设备工具。"""
    global _graph, _device_tools
    if _graph is None:
        _device_tools = await load_device_tools()
        logger.info("[graph] 设备工具 %d 个", len(_device_tools))
        _graph = build_graph(_device_tools)
    return _graph
