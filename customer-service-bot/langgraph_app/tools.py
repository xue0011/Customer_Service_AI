"""LangChain 工具层：用 @tool 声明，参数 schema 由类型注解自动生成。

安全点（对齐旧版 src/tools/security.py）：
- 订单工具必须校验 customer_id 归属，防 IDOR；
- 高风险工具（create_return）超过阈值时返回 NEEDS_APPROVAL 标记，
  由图的 risk_gate 节点转成人工审批（interrupt）；
- 每个 Agent 只绑定自己的工具白名单（售前拿不到退款/退货工具）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from .config import DATA_DIR, get_settings
from .skill_registry import get_registry

APPROVAL_MARKER = "[[NEEDS_APPROVAL]]"

# 演示数据：真实部署时由 data/orders/*.json 或订单服务提供
SAMPLE_ORDERS: dict[str, dict[str, Any]] = {
    "ORD-20251101-001": {
        "order_id": "ORD-20251101-001",
        "customer_id": "cust_001",
        "customer_name": "李雷",
        "status": "运输中",
        "amount": 299.0,
        "items": [{"title": "小鲸鱼降噪耳机 Pro", "qty": 1, "price": 299.0}],
        "logistics": {"carrier": "顺丰速运", "tracking_no": "SF1234567890", "latest": "杭州转运中心"},
        "refund": None,
    },
    "ORD-20251102-002": {
        "order_id": "ORD-20251102-002",
        "customer_id": "cust_001",
        "customer_name": "李雷",
        "status": "已签收",
        "amount": 1299.0,
        "items": [{"title": "小鲸鱼智能空气净化器", "qty": 1, "price": 1299.0}],
        "logistics": {"carrier": "京东物流", "tracking_no": "JD9988776655", "latest": "已签收（本人）"},
        "refund": {"refund_id": "REF-20251103-001", "status": "审核中"},
    },
    "ORD-20251103-003": {
        "order_id": "ORD-20251103-003",
        "customer_id": "cust_002",
        "customer_name": "韩梅梅",
        "status": "待发货",
        "amount": 89.0,
        "items": [{"title": "小鲸鱼桌面氛围灯", "qty": 1, "price": 89.0}],
        "logistics": None,
        "refund": None,
    },
}

_ORDER_ID = re.compile(r"ORD-\d{8}-\d{3}", re.I)


def _all_orders() -> dict[str, dict[str, Any]]:
    """JSON 订单目录存在时叠加，便于沿用旧仓库 data/。"""
    orders = dict(SAMPLE_ORDERS)
    orders_dir = DATA_DIR / "orders"
    if orders_dir.is_dir():
        for file in orders_dir.glob("*.json"):
            try:
                order = json.loads(file.read_text(encoding="utf-8"))
                orders[order["order_id"]] = order
            except Exception:  # noqa: BLE001 - 演示数据容错
                continue
    return orders


def _owned(order_id: str, customer_id: str) -> tuple[dict[str, Any] | None, str]:
    order = _all_orders().get(order_id.upper())
    if order is None:
        return None, f"未找到订单 {order_id}"
    if customer_id and order.get("customer_id") != customer_id:
        # 不泄露订单是否存在之外的信息
        return None, "权限不足：该订单不属于当前顾客"
    return order, ""


@tool
def order_query(order_id: str, customer_id: str) -> str:
    """查询订单详情（状态、商品、金额、物流、退款进度）。只能查询当前顾客自己的订单。"""
    order, error = _owned(order_id, customer_id)
    if order is None:
        return error
    items = "、".join(f"{i['title']}x{i['qty']}" for i in order.get("items", []))
    return (
        f"订单 {order['order_id']} | 状态: {order['status']} | 金额: ¥{order['amount']} | "
        f"商品: {items}"
    )


@tool
def logistics_query(order_id: str, customer_id: str) -> str:
    """查询订单物流轨迹（快递公司、运单号、最新节点）。"""
    order, error = _owned(order_id, customer_id)
    if order is None:
        return error
    logistics = order.get("logistics")
    if not logistics:
        return f"订单 {order['order_id']} 暂无物流信息（状态: {order['status']}）"
    return (
        f"{logistics['carrier']} {logistics['tracking_no']} | 最新: {logistics['latest']}"
    )


@tool
def refund_query(order_id: str, customer_id: str) -> str:
    """查询退款单状态。"""
    order, error = _owned(order_id, customer_id)
    if order is None:
        return error
    refund = order.get("refund")
    if not refund:
        return f"订单 {order['order_id']} 没有进行中的退款"
    return f"退款单 {refund['refund_id']} | 状态: {refund['status']}"


@tool
def create_return(order_id: str, customer_id: str, reason: str) -> str:
    """为顾客创建退货申请。金额超过阈值的退货不会直接生效，需要人工审批。"""
    order, error = _owned(order_id, customer_id)
    if order is None:
        return error
    amount = float(order.get("amount", 0))
    if amount > get_settings().return_approve_threshold:
        payload = {
            "action": "create_return",
            "order_id": order["order_id"],
            "customer_id": customer_id,
            "amount": amount,
            "reason": reason,
        }
        return APPROVAL_MARKER + json.dumps(payload, ensure_ascii=False)
    return (
        f"已创建退货申请：订单 {order['order_id']}，原因「{reason}」，"
        f"工单号 TK-{order['order_id'][-6:]}，预计 48 小时内退款"
    )


@tool
def search_knowledge_base(query: str) -> str:
    """检索商品 FAQ 与售后政策知识库，返回最相关的片段及来源。"""
    hits: list[tuple[str, str]] = []
    kb_dir = DATA_DIR / "policies"
    if kb_dir.is_dir():
        for file in kb_dir.glob("*.md"):
            text = file.read_text(encoding="utf-8", errors="ignore")
            for block in text.split("\n\n"):
                if any(token in block for token in query.split() if len(token) > 1):
                    hits.append((file.name, block.strip()))
    if not hits:
        fallback = {
            "七天无理由": "签收后 7 天内可无理由退货，商品需保持完好，运费由顾客承担。",
            "运费": "质量问题退换货运费商家承担；无理由退货运费顾客承担。",
            "保修": "整机保修 1 年，人为损坏不在保修范围内。",
            "发货": "现货商品 48 小时内发货，预售商品以详情页为准。",
        }
        hits = [(name, text) for name, text in fallback.items() if name in query]
    if not hits:
        return "知识库中未检索到相关内容，建议转人工确认。"
    return "\n\n".join(f"【来源: {name}】{text}" for name, text in hits[:3])


@tool
def load_skill(skill_name: str) -> str:
    """按名称加载一个 Skill 的完整操作手册（只在你需要该领域详细流程时调用）。"""
    try:
        return get_registry().load(skill_name)
    except KeyError as exc:
        return str(exc)


# 工具白名单：售前拿不到售后/退款工具
PRESALES_TOOLS = [search_knowledge_base, order_query, load_skill]
AFTERSALES_TOOLS = [
    order_query,
    logistics_query,
    refund_query,
    create_return,
    search_knowledge_base,
    load_skill,
]
DEVICE_TOOLS = [load_skill, search_knowledge_base]
