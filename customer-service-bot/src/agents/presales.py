"""
售前 Agent
─────────
负责处理售前咨询，包括：
  - 产品信息查询（规格、价格、库存）
  - 产品对比和推荐
  - 促销活动查询
  - 使用场景咨询
  - 配送政策咨询
"""

from __future__ import annotations

import re

from ..config.schema import AgentContext, Response
from .base import BaseAgent

# 尺码关键词
_SIZE_PATTERN = re.compile(r"\b(XS|S|M|L|XL|XXL|XXXL)\b", re.IGNORECASE)
# 价格区间关键词（如 "300-500" / "300到500" / "300元到500元"）
_PRICE_PATTERN = re.compile(r"(\d{2,5})\s*(?:元)?\s*(?:[-到~至])\s*(\d{2,5})\s*(?:元)?")
# 品类关键词
_CATEGORY_KEYWORDS = ["连衣裙", "衬衫", "外套", "裤子", "耳机", "音箱", "保温杯", "收纳", "家居"]


class PresalesAgent(BaseAgent):
    """售前客服 Agent。

    核心能力：
      - 从知识库检索产品信息
      - RAG 搜索（文本 + 图片）
      - 根据顾客需求推荐产品
      - 对比不同产品特性
    """

    # ── 系统提示词 ────────────────────────────────────────────────────────

    async def _get_system_prompt(self) -> str:
        return """你是一个专业的售前客服助手，负责帮助顾客了解产品并做出购买决策。

## 你的职责
1. 回答产品相关问题（规格、材质、尺寸、颜色等）
2. 提供产品价格和促销信息
3. 根据顾客需求推荐合适的产品
4. 对比不同产品的优缺点
5. 解答配送、支付等购买前问题
6. 提供使用场景建议

## 工作原则
- **专业准确**：回答必须基于知识库中的真实信息，不确定时如实告知
- **热情耐心**：保持友好态度，主动了解顾客需求
- **引导成交**：在合适时机引导顾客下单，但不要过度推销
- **结构化回复**：产品信息用清晰的结构呈现，方便顾客阅读

## 回复格式
- 产品推荐时，列出产品名称、价格、核心卖点
- 对比产品时，用表格或列表呈现差异
- 涉及价格的，注明是否包含运费、是否有优惠
- 结尾可以适当引导：如"需要我帮您下单吗？"

## 注意事项
- 不要承诺无法兑现的事情（如"明天一定到货"）
- 不要贬低竞品，只客观介绍自家产品优势
- 遇到无法回答的问题，引导顾客联系人工客服
- 不要透露成本价、供应商等敏感商业信息"""

    # ── 默认工具 ────────────────────────────────────────────────────────

    def _get_default_tools(self) -> list[str]:
        return ["knowledge_base", "rag_search", "order_query"]

    # ── 钩子方法 ────────────────────────────────────────────────────────

    async def _preprocess(self, context: AgentContext) -> AgentContext:
        """售前预处理：提取尺码、价格区间、品类关键词，增强上下文。"""
        content = context.message.content

        sizes = _SIZE_PATTERN.findall(content)
        price_match = _PRICE_PATTERN.search(content)
        categories = [kw for kw in _CATEGORY_KEYWORDS if kw in content]

        if sizes:
            context.message.metadata["mentioned_sizes"] = [s.upper() for s in sizes]
        if price_match:
            context.message.metadata["price_range"] = (float(price_match.group(1)), float(price_match.group(2)))
        if categories:
            context.message.metadata["mentioned_categories"] = categories

        return context

    async def _postprocess(self, response: Response, context: AgentContext) -> Response:
        """售前后处理：添加推荐引导语等。"""
        # 可在此添加引导话术
        if "推荐" in response.content and "下单" not in response.content:
            response.content += "\n\n如有需要，我可以帮您下单哦～"
        return response
