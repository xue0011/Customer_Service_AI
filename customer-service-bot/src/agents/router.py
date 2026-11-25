"""路由 Agent：意图分类 + 置信度门限 + 目标 Agent 选择（验收4）。

调用链：RouterAgent.route → 专用 Agent(presales/aftersales) → ToolRegistry。
设计选择：复用 IntentRouter（关键词→LLM→兜底），本 Agent 增加置信度门限与转人工标记，
避免低置信度直接执行高风险工具。替代方案：LLM function-calling 做工具级路由（更灵活
但更慢更贵）——P1 用轻量分类器。
"""

from __future__ import annotations

from loguru import logger

from ..classifier.router import IntentRouter
from ..config.schema import AppConfig, Intent, Message


class RouterAgent:
    """路由 Agent —— 调用链起点。"""

    def __init__(self, config: AppConfig, confidence_threshold: float = 0.5) -> None:
        self.config = config
        self._router = IntentRouter(config.classifier)
        self._confidence_threshold = confidence_threshold

    async def initialize(self) -> None:
        logger.info("[RouterAgent] 就绪")

    async def route(self, message: Message) -> dict:
        """分类并选择目标 Agent。返回 {intent, confidence, target, escalate, reason}。"""
        intent, confidence = await self._router.classify(message)
        target = self._select_agent(intent)
        escalate = confidence < self._confidence_threshold
        if escalate:
            logger.info(
                f"[RouterAgent] 低置信度 {intent.value}({confidence:.2f}) → 建议转人工"
            )
        return {
            "intent": intent.value,
            "confidence": confidence,
            "target": target,
            "escalate": escalate,
            "reason": "low_confidence" if escalate else "ok",
        }

    @staticmethod
    def _select_agent(intent: Intent) -> str:
        mapping = {Intent.PRESALES: "presales", Intent.AFTERSALES: "aftersales"}
        return mapping.get(intent, "chitchat")
