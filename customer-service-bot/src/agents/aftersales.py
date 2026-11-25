"""
售后 Agent
─────────
负责处理售后问题，包括：
  - 订单状态查询（发货、物流、送达）
  - 退换货处理
  - 退款查询
  - 投诉与建议
  - 产品质量问题
  - 保修与维修
"""

from __future__ import annotations

import re

from ..config.schema import AgentContext, Response
from .base import BaseAgent

# 订单号正则：ORD-YYYYMMDD-NNN
_ORDER_ID_PATTERN = re.compile(r"ORD-\d{8}-\d{3}", re.IGNORECASE)
# 手机号正则：1开头的11位数字
_PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")
# 退款单号正则：REF-YYYYMMDD-NNN
_REFUND_ID_PATTERN = re.compile(r"REF-\d{8}-\d{3}", re.IGNORECASE)


class AftersalesAgent(BaseAgent):
    """售后客服 Agent。

    核心能力：
      - 查询订单状态和物流信息
      - 处理退换货申请
      - 查询退款进度
      - 记录和升级投诉
      - 查阅售后政策（退换货规则、保修条款等）
    """

    # ── 系统提示词 ────────────────────────────────────────────────────────

    async def _get_system_prompt(self) -> str:
        return """你是一个专业的售后客服助手，负责处理顾客的售后问题。

## 你的职责
1. 查询订单状态（待付款、已发货、运输中、已签收等）
2. 查询物流信息（快递公司、运单号、当前位置）
3. 处理退换货申请（判断是否符合条件、告知流程）
4. 查询退款进度
5. 处理产品质量投诉
6. 解答保修和维修相关问题
7. 记录顾客建议和反馈

## 工作原则
- **耐心共情**：售后顾客往往有情绪，先理解再解决问题
- **高效解决**：优先给出可操作的解决方案，而不是推诿
- **透明诚实**：实事求是说明问题原因和处理时限
- **主动跟进**：需要升级的问题要明确告知顾客后续流程

## 处理流程
1. 先确认顾客身份和订单号
2. 了解问题详情（发生了什么、期望怎么解决）
3. 查询相关订单和政策信息
4. 给出明确解决方案和时间节点
5. 记录问题，必要时升级处理

## 回复格式
- 先表达理解和歉意（如适用）
- 说明问题原因（如果已知）
- 给出解决方案和具体步骤
- 告知预计处理时间
- 留下进一步联系的方式

## 退款/退货标准话术
- 符合退换货条件：告知流程、地址、预计退款时间
- 不符合条件：礼貌说明原因，提供替代方案（换货、优惠券等）
- 质量问题：真诚道歉，优先处理，必要时补偿

## 注意事项
- 不要轻易承诺赔偿金额，超出权限的需升级处理
- 不要指责顾客，即使问题出在顾客方
- 涉及法律问题的（如食品安全），按公司合规流程处理
- 不要透露内部流程、成本等敏感信息"""

    # ── 默认工具 ────────────────────────────────────────────────────────

    def _get_default_tools(self) -> list[str]:
        return ["order_query", "logistics_query", "refund_query", "modify_order", "return_apply", "knowledge_base"]

    # ── 钩子方法 ────────────────────────────────────────────────────────

    async def _preprocess(self, context: AgentContext) -> AgentContext:
        """售后预处理：从消息中提取订单号、手机号、退款单号。"""
        content = context.message.content

        order_ids = _ORDER_ID_PATTERN.findall(content)
        phones = _PHONE_PATTERN.findall(content)
        refund_ids = _REFUND_ID_PATTERN.findall(content)

        if order_ids:
            context.message.metadata["extracted_order_ids"] = [oid.upper() for oid in order_ids]
        if phones:
            # 避免重复
            context.message.metadata["extracted_phones"] = list({p for p in phones})
        if refund_ids:
            context.message.metadata["extracted_refund_ids"] = [rid.upper() for rid in refund_ids]

        return context

    async def _postprocess(self, response: Response, context: AgentContext) -> Response:
        """售后后处理：补充工单/退款单引用信息。"""
        # 如果消息中提到了工单（通过 return_apply 生成），在回复末尾标注参考信息
        metadata = context.message.metadata
        if metadata.get("last_ticket_id"):
            if "TICKET-" not in response.content:
                response.content += f"\n\n📋 工单号: {metadata['last_ticket_id']}"
        return response
