"""
意图路由器（Intent Router）
──────────────────────────
负责分析顾客消息的意图，将消息分配到正确的 Agent。

实现方式：
  1. 关键词快速匹配（无需 LLM 调用，毫秒级）
  2. LLM 精细分类（处理复杂/模糊消息）
  3. 规则兜底（确保分类结果稳定）
"""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from ..config.schema import Intent, LLMConfig, Message
from ..core.runner import LLMClient
from .prompts import INTENT_CLASSIFICATION_PROMPT


class IntentRouter:
    """意图路由器 —— 对消息进行分类，返回意图和置信度。"""

    # ── 关键词规则（快速匹配，无需 LLM） ────────────────────────────────

    AFTERSALES_KEYWORDS = [
        # 订单相关
        r"订单", r"发货", r"物流", r"快递", r"单号", r"运单",
        r"还没到", r"什么时候到", r"到哪了",
        # 退款退货
        r"退款", r"退货", r"换货", r"退换", r"退钱",
        r"不想要了", r"买错了", r"申请退",
        # 质量问题
        r"坏了", r"破损", r"瑕疵", r"质量", r"有问题",
        r"不好用", r"不能用", r"用不了",
        # 已购买暗示
        r"我买了", r"收到了", r"买到的", r"收到货",
        r"用了几[天次]", r"穿了几[天次]",
        # 投诉
        r"投诉", r"差评", r"举报",
        # 修改订单
        r"改地址", r"修改地址", r"换颜色", r"换尺码",
    ]

    PRESALES_KEYWORDS = [
        # 产品询问
        r"多少钱", r"价格", r"怎么卖", r"有.*吗",
        r"有没有", r"有什么", r"哪些",
        # 产品属性
        r"材质", r"尺寸", r"颜色", r"规格", r"参数",
        r"多大", r"多重", r"什么.*材料",
        # 推荐
        r"推荐", r"哪个好", r"适合", r"选哪个",
        # 购买前
        r"想买", r"想入手", r"准备买", r"考虑",
        # 配送
        r"包邮", r"运费", r"几天到", r"配送",
        # 支付
        r"怎么付款", r"支付方式", r"支持.*支付",
        # 促销
        r"活动", r"优惠", r"打折", r"满减", r"优惠券",
    ]

    CHITCHAT_KEYWORDS = [
        r"^你好", r"^在吗", r"^嗨", r"^hi", r"^hello",
        r"谢谢", r"感谢", r"再见", r"拜拜",
        r"^嗯", r"^哦", r"^好$",
    ]

    def __init__(self, llm_config: LLMConfig | None = None) -> None:
        self.llm_client = LLMClient(llm_config) if llm_config else None
        # 编译正则
        self._aftersales_re = [re.compile(kw) for kw in self.AFTERSALES_KEYWORDS]
        self._presales_re = [re.compile(kw) for kw in self.PRESALES_KEYWORDS]
        self._chitchat_re = [re.compile(kw) for kw in self.CHITCHAT_KEYWORDS]

    async def classify(self, message: Message) -> tuple[Intent, float]:
        """分类消息意图。

        Returns:
            (Intent, confidence): 意图和置信度 (0.0-1.0)
        """
        content = message.content.strip()

        # ── 第一层：关键词快速匹配 ────────────────────────────────────
        kw_result = self._keyword_classify(content)
        if kw_result is not None:
            intent, confidence = kw_result
            logger.debug(f"[Router] 关键词匹配: {intent.value} (confidence={confidence})")
            return intent, confidence

        # ── 第二层：LLM 精细分类 ───────────────────────────────────────
        if self.llm_client:
            llm_result = await self._llm_classify(content)
            if llm_result is not None:
                intent, confidence = llm_result
                logger.debug(f"[Router] LLM 分类: {intent.value} (confidence={confidence})")
                return intent, confidence

        # ── 第三层：兜底 ───────────────────────────────────────────────
        logger.debug("[Router] 兜底分类: chitchat")
        return Intent.CHITCHAT, 0.3

    def _keyword_classify(self, content: str) -> tuple[Intent, float] | None:
        """关键词匹配分类。"""

        # 售后关键词
        aftersales_hits = sum(1 for r in self._aftersales_re if r.search(content))
        # 售前关键词
        presales_hits = sum(1 for r in self._presales_re if r.search(content))
        # 闲聊关键词
        chitchat_hits = sum(1 for r in self._chitchat_re if r.search(content))

        # 需要一定数量的关键词命中才算
        if aftersales_hits >= 2 and aftersales_hits > presales_hits:
            return Intent.AFTERSALES, min(0.85, 0.5 + aftersales_hits * 0.1)
        if presales_hits >= 2 and presales_hits > aftersales_hits:
            return Intent.PRESALES, min(0.85, 0.5 + presales_hits * 0.1)
        if chitchat_hits >= 1 and aftersales_hits == 0 and presales_hits == 0:
            return Intent.CHITCHAT, 0.9

        # 单一强信号
        if aftersales_hits == 1 and presales_hits == 0:
            return Intent.AFTERSALES, 0.6
        if presales_hits == 1 and aftersales_hits == 0:
            return Intent.PRESALES, 0.6

        return None  # 无法通过关键词确定

    async def _llm_classify(self, content: str) -> tuple[Intent, float] | None:
        """LLM 精细分类。"""
        try:
            messages = [
                {"role": "system", "content": INTENT_CLASSIFICATION_PROMPT},
                {"role": "user", "content": content},
            ]
            raw = await self.llm_client.chat(messages, temperature=0.1)
            text = raw["choices"][0]["message"].get("content", "")

            # 提取 JSON
            result = self._parse_json(text)
            if result:
                intent_str = result.get("intent", "chitchat")
                confidence = float(result.get("confidence", 0.5))
                intent = Intent(intent_str)
                return intent, confidence
        except Exception:
            logger.exception("[Router] LLM 分类失败")

        return None

    def _parse_json(self, text: str) -> dict[str, Any] | None:
        """从文本中提取 JSON。"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 块
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None
