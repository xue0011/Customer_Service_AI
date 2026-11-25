"""图节点：每个函数只做一件事，状态进、增量状态出，方便单独测试与替换。

节点清单
--------
input_guard → router → presales / aftersales / device / chitchat
                     ↘ escalate（低置信度转人工）
agent → risk_gate → approval（interrupt 人工审批）/ output_guard → END
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.prebuilt import create_react_agent
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from . import tools as T
from .config import get_settings
from .guardrails import check_input, check_output
from .llm import build_llm
from .skill_registry import get_registry
from .state import AgentState

logger = logging.getLogger(__name__)

_ORDER_ID = re.compile(r"ORD-\d{8}-\d{3}", re.I)
_SOURCE = re.compile(r"【来源[:：]\s*([^】]+)】")

BRAND = "小鲸鱼优选"

SKILL_BY_INTENT = {
    "presales": "presales",
    "aftersales": "aftersales",
    "device": "device-control",
}

PROMPT = """你是「{brand}」的电商智能客服（当前领域：{intent}），服务顾客 {customer_id}。

## 本领域 Skill 手册（必须遵守）
{skill}

## 工具使用规则
1. 订单/物流/退款工具必须传 customer_id，工具会做归属校验；被拒绝时如实告知，不要猜测。
2. 退货金额超过阈值时工具会返回审批标记，你只需告诉顾客「已提交人工审核」。
3. 设备控制工具来自 MCP Server，只能操作顾客自己的设备；不确定时先查询，绝不编造设备或状态。
4. 知识库返回带「来源」，结论后要保留来源标注。

## 回复风格
先共情/确认问题 → 给结论与步骤 → 说明时效 → 需要时给出下一步。
不要承诺超出权限的赔付，不要透露内部成本或流程。"""


# ── 路由 ──────────────────────────────────────────────────────────────────

_ROUTE_KEYWORDS: dict[str, list[str]] = {
    "aftersales": ["退款", "退货", "换货", "物流", "快递", "订单", "发票", "保修", "维修",
                   "投诉", "坏了", "少发", "漏发", "签收", "退款"],
    "device": ["灯", "亮度", "色温", "空调", "净化器", "插座", "设备", "智能家居",
               "回家模式", "离家模式"],
    "presales": ["推荐", "价格", "多少钱", "优惠", "库存", "有货", "尺码", "颜色",
                 "发货时间", "适合", "对比", "怎么选", "买"],
}


class RouteDecision(BaseModel):
    intent: Literal["presales", "aftersales", "device", "chitchat"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


def _rule_route(text: str) -> tuple[str, int]:
    best, hits = "chitchat", 0
    for intent, words in _ROUTE_KEYWORDS.items():
        count = sum(1 for word in words if word in text)
        if count > hits:
            best, hits = intent, count
    return best, hits


def route_node(state: AgentState) -> dict[str, Any]:
    text = state.get("text", "")
    llm = build_llm()
    if llm is not None:
        try:
            decision = llm.with_structured_output(RouteDecision).invoke(
                [
                    SystemMessage(content="你是电商客服意图分类器。只输出 intent/confidence/reason。"),
                    HumanMessage(content=text),
                ]
            )
            return {
                "intent": decision.intent,
                "confidence": decision.confidence,
                "route_reason": decision.reason or "llm",
            }
        except Exception as exc:  # noqa: BLE001 - 路由失败不影响主流程
            logger.warning("[router] LLM 分类失败，回退关键词: %s", exc)

    intent, hits = _rule_route(text)
    confidence = 0.9 if hits >= 3 else 0.75 if hits == 2 else 0.6 if hits == 1 else 0.3
    return {"intent": intent, "confidence": confidence, "route_reason": f"keyword×{hits}"}


def after_route(state: AgentState) -> str:
    if state.get("confidence", 1.0) < get_settings().confidence_threshold:
        return "escalate"
    return state.get("intent", "chitchat")


# ── 护栏 ──────────────────────────────────────────────────────────────────

def input_guard_node(state: AgentState) -> dict[str, Any]:
    text = state.get("text") or _last_human(state.get("messages", []))
    ok, reason = check_input(text, get_settings().max_message_chars)
    return {"text": text, "blocked": not ok, "block_reason": reason}


def reject_node(state: AgentState) -> dict[str, Any]:
    reply = f"抱歉，这条消息暂时无法处理（{state.get('block_reason', '')}）。可以换个说法，或联系人工客服。"
    return {"reply": reply, "escalated": True, "messages": [AIMessage(content=reply)]}


def escalate_node(state: AgentState) -> dict[str, Any]:
    reply = (
        f"这个问题我不太确定（置信度 {state.get('confidence', 0):.2f}），"
        "已为你转接人工客服，预计 1 分钟内响应。如有订单号可以先发我，我帮你查。"
    )
    return {"reply": reply, "escalated": True, "messages": [AIMessage(content=reply)]}


def output_guard_node(state: AgentState) -> dict[str, Any]:
    reply = state.get("reply") or _last_ai(state.get("messages", []))
    _, reason, sanitized = check_output(reply)
    citations = list(dict.fromkeys(state.get("citations") or []))
    if citations:
        sanitized += "\n\n参考来源：" + "；".join(citations)
    if reason:
        sanitized += "\n（内容已按合规规则调整）"

    last = (state.get("messages") or [None])[-1]
    extra: list = []
    if isinstance(last, AIMessage) and last.content != sanitized:
        extra = [RemoveMessage(id=last.id), AIMessage(content=sanitized)]
    return {"reply": sanitized, "messages": extra}


# ── Agent 节点 ────────────────────────────────────────────────────────────

def make_agent_node(intent: str, device_tools: list | None = None):
    """工厂：为每个领域生成一个 ReAct Agent 节点（LangGraph prebuilt）。"""

    async def node(state: AgentState) -> dict[str, Any]:
        skill_name = SKILL_BY_INTENT.get(intent, "")
        skill_body = _skill_body(skill_name)
        llm = build_llm()
        tools = _tools_for(intent, device_tools or [])

        if llm is None:
            return await _offline_agent(state, intent, skill_body)

        agent = create_react_agent(
            llm,
            tools,
            prompt=PROMPT.format(
                brand=BRAND,
                intent=intent,
                customer_id=state.get("customer_id", "匿名顾客"),
                skill=skill_body or "（本领域暂无 Skill）",
            ),
        )
        result = await agent.ainvoke({"messages": state["messages"]})
        messages = result["messages"]
        reply = messages[-1].content if isinstance(messages[-1], AIMessage) else ""
        pending = _find_approval(messages)

        return {
            "messages": [AIMessage(content=reply)],
            "reply": reply,
            "skill": skill_name,
            "tool_calls": [m.name for m in messages if isinstance(m, ToolMessage)],
            "citations": _citations(messages),
            "pending_action": pending or {},
            "requires_approval": bool(pending),
        }

    return node


def chitchat_node(state: AgentState) -> dict[str, Any]:
    text = state.get("text", "")
    llm = build_llm()
    if llm is not None:
        try:
            reply = llm.invoke(
                [
                    SystemMessage(content=f"你是{BRAND}的客服，友好简短地回应寒暄并引导用户说明需求。"),
                    HumanMessage(content=text),
                ]
            ).content
            return {"reply": reply, "messages": [AIMessage(content=reply)]}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[chitchat] LLM 失败: %s", exc)
    reply = f"你好，我是{BRAND}智能客服 👋 可以帮你查订单物流、处理退换货，也能控制家里的智能设备。"
    return {"reply": reply, "messages": [AIMessage(content=reply)]}


# ── 风险闸门 / 人工审批 ───────────────────────────────────────────────────

def risk_gate_node(state: AgentState) -> dict[str, Any]:
    action = state.get("pending_action") or {}
    if not action:
        return {"requires_approval": False}
    threshold = get_settings().return_approve_threshold
    return {
        "requires_approval": True,
        "approval_reason": f"退货金额 ¥{action.get('amount')} 超过自动审批阈值 ¥{threshold}",
    }


def approval_node(state: AgentState) -> dict[str, Any]:
    """interrupt 挂起图，直到 API 用 Command(resume={"approved": ...}) 恢复。"""
    action = state.get("pending_action") or {}
    order_id = action.get("order_id", "")

    decision = interrupt(
        {
            "type": "approval",
            "title": "退货申请需要人工审批",
            "action": action,
            "reason": state.get("approval_reason", ""),
        }
    )
    approved = decision.get("approved") if isinstance(decision, dict) else bool(decision)

    if approved:
        reply = (
            f"✅ 审批通过：订单 {order_id} 的退货申请已提交，"
            f"工单号 TK-{order_id[-6:]}，预计 48 小时内完成退款。"
        )
        return {"approved": True, "requires_approval": False,
                "reply": reply, "messages": [AIMessage(content=reply)]}

    reply = f"已取消：订单 {order_id} 的退货申请未提交。如需继续，请补充问题描述后重试。"
    return {"approved": False, "requires_approval": False,
            "reply": reply, "messages": [AIMessage(content=reply)]}


# ── 离线规则模式（无 LLM Key 时保证 demo 可跑） ─────────────────────────────

async def _offline_agent(state: AgentState, intent: str, skill_body: str) -> dict[str, Any]:
    text = state.get("text", "")
    customer_id = state.get("customer_id", "")
    evidence: list[str] = []
    used: list[str] = []

    match = _ORDER_ID.search(text)
    if match:
        order_id = match.group(0).upper()
        if "物流" in text or "快递" in text:
            evidence.append(T.logistics_query.invoke({"order_id": order_id, "customer_id": customer_id}))
            used.append("logistics_query")
        elif "退款" in text:
            evidence.append(T.refund_query.invoke({"order_id": order_id, "customer_id": customer_id}))
            used.append("refund_query")
        else:
            evidence.append(T.order_query.invoke({"order_id": order_id, "customer_id": customer_id}))
            used.append("order_query")
    elif intent == "presales":
        evidence.append(T.search_knowledge_base.invoke({"query": text}))
        used.append("search_knowledge_base")
    elif intent == "device":
        evidence.append("设备控制需要先启动 MCP Server：见 mcp_servers.json 与 MiDeviceController/ControlXiaomiDevices/mcp_server.py")
    elif intent == "aftersales":
        evidence.append("请提供订单号（形如 ORD-20251101-001），我帮你查订单、物流或退款进度。")

    head = skill_body.splitlines()[0].lstrip("# ").strip() if skill_body else intent
    reply = "\n".join([f"[离线规则模式 · {head}]", *evidence])
    citations = [m for line in evidence for m in _SOURCE.findall(line)]
    return {
        "messages": [AIMessage(content=reply)],
        "reply": reply,
        "skill": SKILL_BY_INTENT.get(intent, ""),
        "tool_calls": used,
        "citations": citations,
        "pending_action": {},
        "requires_approval": False,
    }


# ── 工具函数 ──────────────────────────────────────────────────────────────

def _tools_for(intent: str, device_tools: list) -> list:
    if intent == "presales":
        return list(T.PRESALES_TOOLS)
    if intent == "aftersales":
        return list(T.AFTERSALES_TOOLS)
    if intent == "device":
        return list(T.DEVICE_TOOLS) + list(device_tools)
    return list(T.DEVICE_TOOLS)


def _skill_body(name: str) -> str:
    if not name:
        return ""
    try:
        return get_registry().load(name)
    except KeyError:
        return ""


def _citations(messages: list) -> list[str]:
    found: list[str] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            found.extend(_SOURCE.findall(str(message.content)))
    return list(dict.fromkeys(found))


def _find_approval(messages: list) -> dict[str, Any] | None:
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and T.APPROVAL_MARKER in str(message.content):
            raw = str(message.content).split(T.APPROVAL_MARKER, 1)[1]
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"raw": raw}
    return None


def _last_human(messages: list) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _last_ai(messages: list) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return str(message.content)
    return ""
