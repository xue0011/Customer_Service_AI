"""FastAPI 入口 —— 与旧版 src/api/server.py 并存，端口不同（默认 8010）。

接口：
    POST /chat                      发起一轮对话（可能停在审批）
    POST /chat/{thread_id}/approve  人工审批后恢复被 interrupt 的图
    GET  /skills                    Skill 目录（渐进式披露的第一级）
    GET  /mcp/tools                 MCP 设备工具清单
    GET  /graph                     状态图 Mermaid 源码
    GET  /health                    健康检查
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from .config import get_settings
from .graph import get_device_tools, get_graph
from .skill_registry import get_registry

app = FastAPI(title="小鲸鱼智能客服 · LangGraph", version="0.1.0")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, description="顾客消息")
    thread_id: str = Field(default="", description="会话ID，留空自动生成")
    customer_id: str = Field(default="cust_001", description="顾客ID，用于订单归属校验")


class ApproveRequest(BaseModel):
    approved: bool
    comment: str = ""


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _payload(result: dict[str, Any], thread_id: str) -> dict[str, Any]:
    interrupts = result.get("__interrupt__") or []
    approval = interrupts[0].value if interrupts else None
    return {
        "thread_id": thread_id,
        "status": "need_approval" if interrupts else "ok",
        "intent": result.get("intent", ""),
        "confidence": result.get("confidence", 0.0),
        "route_reason": result.get("route_reason", ""),
        "skill": result.get("skill", ""),
        "reply": result.get("reply", ""),
        "citations": result.get("citations", []),
        "tool_calls": result.get("tool_calls", []),
        "escalated": result.get("escalated", False),
        "approval": approval,
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "llm_mode": "llm" if settings.llm_enabled else "offline",
        "model": settings.model if settings.llm_enabled else None,
        "mcp_tools": [t.name for t in get_device_tools()],
    }


@app.post("/chat")
async def chat(req: ChatRequest) -> dict[str, Any]:
    graph = await get_graph()
    thread_id = req.thread_id or f"t-{uuid.uuid4().hex[:8]}"
    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content=req.message)],
            "text": req.message,
            "customer_id": req.customer_id,
            "thread_id": thread_id,
        },
        _config(thread_id),
    )
    return _payload(result, thread_id)


@app.post("/chat/{thread_id}/approve")
async def approve(thread_id: str, req: ApproveRequest) -> dict[str, Any]:
    graph = await get_graph()
    result = await graph.ainvoke(
        Command(resume={"approved": req.approved, "comment": req.comment}),
        _config(thread_id),
    )
    return _payload(result, thread_id)


@app.get("/skills")
async def skills() -> dict[str, Any]:
    return {"skills": get_registry().catalog()}


@app.get("/mcp/tools")
async def mcp_tools() -> dict[str, Any]:
    return {
        "tools": [
            {"name": t.name, "description": (t.description or "").strip()}
            for t in get_device_tools()
        ]
    }


@app.get("/graph")
async def graph_source() -> dict[str, str]:
    graph = await get_graph()
    return {"mermaid": graph.get_graph().draw_mermaid()}
