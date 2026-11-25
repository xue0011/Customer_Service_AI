"""
消息总线（Message Bus）
─────────────────────
借鉴 nanobot 的 MessageBus 设计，提供发布/订阅模式的消息中枢。

职责：
  - 接收来自各渠道（淘宝、京东、拼多多、得物）的原始消息
  - 将消息路由到分类器进行意图识别
  - 根据意图分发到对应的 Agent
  - 收集 Agent 回复，经护栏检查后回传渠道
  - 记录所有消息流转日志
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from loguru import logger

from ..config.schema import Intent, Message, Response

# ─── 类型别名 ──────────────────────────────────────────────────────────────

Handler = Callable[["Envelope"], Awaitable[Response | None]]
Middleware = Callable[["Envelope", Handler], Awaitable[Response | None]]


# ─── 消息信封 ──────────────────────────────────────────────────────────────

@dataclass
class Envelope:
    """消息在总线中流转时的包装。"""
    message: Message
    intent: Intent | None = None
    intent_confidence: float = 0.0
    agent_name: str = ""
    response: Response | None = None
    guardrail_flagged: bool = False
    guardrail_reason: str = ""
    trace: list[str] = field(default_factory=list)      # 流转追踪
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


# ─── 消息总线 ──────────────────────────────────────────────────────────────

class MessageBus:
    """消息总线 —— 系统的中枢神经系统。

    使用方式：
        bus = MessageBus()
        bus.subscribe("classify", my_classifier)
        bus.subscribe("presales", presales_agent)
        bus.subscribe("aftersales", aftersales_agent)
        response = await bus.dispatch(message)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}
        self._middlewares: list[Middleware] = []
        self._history: list[Envelope] = []               # 消息历史记录
        self._lock = asyncio.Lock()

    # ── 订阅管理 ──────────────────────────────────────────────────────────

    def subscribe(self, topic: str, handler: Handler) -> None:
        """订阅某个主题。"""
        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(handler)
        logger.debug(f"[MessageBus] {handler.__name__} 订阅了主题 '{topic}'")

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        """取消订阅。"""
        if topic in self._handlers:
            self._handlers[topic] = [h for h in self._handlers[topic] if h != handler]
            logger.debug(f"[MessageBus] {handler.__name__} 取消订阅主题 '{topic}'")

    def add_middleware(self, middleware: Middleware) -> None:
        """添加中间件（在消息处理链中插入逻辑）。"""
        self._middlewares.append(middleware)

    # ── 消息分发 ──────────────────────────────────────────────────────────

    async def dispatch(self, message: Message) -> Response | None:
        """分发一条消息，走完整流程：分类 → Agent → 护栏 → 返回。"""
        envelope = Envelope(message=message)
        envelope.trace.append("bus:received")

        logger.info(f"[MessageBus] 收到消息 id={message.id} from={message.platform}")

        # 构建处理链：分类 → 护栏 → Agent
        async def pipeline(env: Envelope) -> Response | None:
            # Step 1: 意图分类
            env.trace.append("bus:classifying")
            await self._notify("classify", env)
            env.trace.append(f"bus:intent={env.intent.value if env.intent else 'unknown'}")

            # Step 2: 根据意图路由到 Agent
            if env.intent in (Intent.PRESALES, Intent.AFTERSALES):
                topic = env.intent.value
                env.trace.append(f"bus:routing_to={topic}")
                await self._notify(topic, env)
            else:
                env.trace.append("bus:chitchat")
                env.agent_name = "chitchat"
                env.response = Response(
                    message_id=message.id,
                    content="你好！请问有什么可以帮您的？售前咨询请描述需求，售后问题请提供订单号。",
                    intent=Intent.CHITCHAT,
                    agent="chitchat",
                )

            # Step 3: 护栏检查
            env.trace.append("bus:guardrail")
            await self._notify("guardrail", env)

            return env.response

        # 应用中间件
        handler: Handler = pipeline
        for mw in reversed(self._middlewares):
            outer = mw
            inner = handler
            handler = lambda env, o=outer, i=inner: o(env, i)

        result = await handler(envelope)

        # 记录历史
        async with self._lock:
            self._history.append(envelope)

        logger.info(
            f"[MessageBus] 消息 id={message.id} 处理完成 "
            f"trace={' → '.join(envelope.trace)}"
        )
        return result

    async def _notify(self, topic: str, envelope: Envelope) -> None:
        """通知所有订阅了 topic 的处理器。"""
        handlers = self._handlers.get(topic, [])
        if not handlers:
            logger.warning(f"[MessageBus] 主题 '{topic}' 没有订阅者")
            return

        for handler in handlers:
            try:
                result = await handler(envelope)
                if result is not None and envelope.response is None:
                    envelope.response = result
            except Exception:
                logger.exception(f"[MessageBus] 处理器 {handler.__name__} 执行出错")

    # ── 查询接口 ──────────────────────────────────────────────────────────

    def get_history(self, limit: int = 50) -> list[Envelope]:
        """获取最近的消息历史。"""
        return self._history[-limit:]

    def get_customer_thread(self, customer_id: str) -> list[Envelope]:
        """获取某客户的消息记录。"""
        return [e for e in self._history if e.message.customer_id == customer_id]

    def reset(self) -> None:
        """清空历史（用于测试）。"""
        self._history.clear()
        self._handlers.clear()
        self._middlewares.clear()
