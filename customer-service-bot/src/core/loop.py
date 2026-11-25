"""
主循环（Loop）
────────────
系统的主入口循环 —— 负责将各组件串联起来：

  接收消息 → 分类 → 调用 Agent → 护栏 → 返回

这是系统的"指挥中心"，自身不处理业务逻辑，只负责编排。
"""

from __future__ import annotations

from loguru import logger

from ..agents.aftersales import AftersalesAgent
from ..agents.base import BaseAgent
from ..agents.presales import PresalesAgent
from ..agents.router import RouterAgent
from ..config.schema import AppConfig, Intent, Message, Response
from ..guardrail.checker import GuardrailChecker
from ..memory.context import ContextBuilder
from ..memory.store import MemoryStore
from ..tools import (
    KnowledgeBaseTool,
    LogisticsQueryTool,
    ModifyOrderTool,
    OrderQueryTool,
    RAGSearchTool,
    RefundQueryTool,
    ReturnApplyTool,
    ToolRegistry,
)
from .bus import Envelope, MessageBus


class CustomerServiceLoop:
    """客服系统主循环 —— 编排所有组件。

    使用方式：
        config = load_config()
        loop = CustomerServiceLoop(config)
        await loop.start()

        # 收到来自某个渠道的消息
        response = await loop.handle_message(message)
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config

        # ── 基础设施 ──────────────────────────────────────────────────
        self.bus = MessageBus()
        self.memory = MemoryStore(config.memory)
        self.context_builder = ContextBuilder(self.memory)

        # ── 路由 Agent（分类 + 置信度门限） ─────────────────────────────
        self.router_agent = RouterAgent(config)

        # ── Agent ─────────────────────────────────────────────────────
        self.agents: dict[str, BaseAgent] = {}
        self._register_agents()

        # ── 护栏 ──────────────────────────────────────────────────────
        self.guardrail = GuardrailChecker(config.guardrail)

        # ── 记忆整理器 ────────────────────────────────────────────────
        from ..memory.consolidator import MemoryConsolidator
        self.consolidator = MemoryConsolidator(
            memory_store=self.memory,
            config=config.memory,
            llm_config=config.classifier,
        )

        # ── 连接总线 ──────────────────────────────────────────────────
        self._wire_bus()

    def _register_agents(self) -> None:
        """注册所有 Agent。"""
        # 创建共享工具注册表
        tool_registry = ToolRegistry()
        data_dir = self.config.data_dir

        # legacy MySQL 仓库已移除；工具层使用异步仓储（src/database/repositories_async）
        order_repo = None
        product_repo = None
        logistics_repo = None
        refund_repo = None
        policy_repo = None
        ticket_repo = None

        # 注册所有工具
        tool_registry.register_many([
            KnowledgeBaseTool(data_dir=data_dir, product_repo=product_repo,
                              faq_repo=None, policy_repo=policy_repo),
            RAGSearchTool(data_dir=data_dir),
            OrderQueryTool(data_dir=data_dir, order_repo=order_repo),
            LogisticsQueryTool(data_dir=data_dir, logistics_repo=logistics_repo),
            RefundQueryTool(data_dir=data_dir, refund_repo=refund_repo),
            ModifyOrderTool(data_dir=data_dir, order_repo=order_repo, product_repo=product_repo),
            ReturnApplyTool(data_dir=data_dir, order_repo=order_repo, product_repo=product_repo,
                            policy_repo=policy_repo, ticket_repo=ticket_repo,
                            threshold=self.config.return_policy.min_amount_auto,
                            return_window=self.config.return_policy.allowed_window_days),
        ])

        # 注册语音转文字工具（仅注册，Agent 不默认使用，通过 /api/speech 调用）
        try:
            from ..tools.speech_to_text import SpeechToTextTool
            tool_registry.register(SpeechToTextTool())
        except Exception as e:
            logger.debug(f"[Loop] 语音转文字工具注册失败（已跳过）: {e}")

        self.agents["presales"] = PresalesAgent(
            config=self.config.presales_agent,
            memory=self.memory,
            tool_registry=tool_registry,
        )
        self.agents["aftersales"] = AftersalesAgent(
            config=self.config.aftersales_agent,
            memory=self.memory,
            tool_registry=tool_registry,
        )
        logger.info(f"[Loop] 已注册 Agent: {list(self.agents.keys())}")

    def _wire_bus(self) -> None:
        """将总线主题与处理器连接。"""
        # 分类
        self.bus.subscribe("classify", self._handle_classify)
        # Agent 分发
        self.bus.subscribe("presales", self._handle_presales)
        self.bus.subscribe("aftersales", self._handle_aftersales)
        # 护栏
        self.bus.subscribe("guardrail", self._handle_guardrail)
        logger.info("[Loop] 总线连接完成")

    # ── 消息总线处理器 ──────────────────────────────────────────────────

    async def _handle_classify(self, envelope: Envelope) -> Response | None:
        """意图分类处理器（RouterAgent：分类 + 置信度门限 + 转人工标记）。"""
        decision = await self.router_agent.route(envelope.message)
        envelope.intent = Intent(decision["intent"])
        envelope.intent_confidence = decision["confidence"]
        if decision.get("escalate"):
            envelope.metadata["escalate"] = True
            envelope.metadata["escalate_reason"] = decision.get("reason", "")
        return None  # 不直接返回，继续流水线

    async def _handle_presales(self, envelope: Envelope) -> Response | None:
        """售前 Agent 处理器。"""
        agent = self.agents["presales"]
        return await self._run_agent(agent, envelope, Intent.PRESALES)

    async def _handle_aftersales(self, envelope: Envelope) -> Response | None:
        """售后 Agent 处理器。"""
        agent = self.agents["aftersales"]
        return await self._run_agent(agent, envelope, Intent.AFTERSALES)

    async def _run_agent(
        self, agent: BaseAgent, envelope: Envelope, intent: Intent
    ) -> Response | None:
        """通用的 Agent 执行包装。"""
        envelope.agent_name = agent.config.name

        # 构建上下文（含记忆）
        context = await self.context_builder.build(
            message=envelope.message,
            customer_id=envelope.message.customer_id,
        )
        context.message.metadata["intent"] = intent.value
        context.message.metadata["agent"] = agent.config.name

        # 注入退货政策到上下文
        context.shop_config["return_policy"] = self.config.return_policy.model_dump()

        # 执行 Agent
        response = await agent.run(context)

        # 保存交互到记忆
        await self.memory.save_interaction(
            customer_id=envelope.message.customer_id,
            thread_id=envelope.message.thread_id,
            user_message=envelope.message.content,
            assistant_message=response.content,
            metadata={"intent": intent.value, "agent": agent.config.name},
        )

        # 持久化会话与消息到 DB（替代进程内内存）
        try:
            from ..database.db import get_session_factory
            from ..database.repositories_async import SessionRepository

            sid = envelope.message.thread_id or envelope.message.customer_id
            async with get_session_factory()() as s:
                srepo = SessionRepository(s)
                await srepo.get_or_create(
                    sid, customer_id=envelope.message.customer_id,
                    channel=str(envelope.message.platform),
                )
                await srepo.append_message(
                    sid, "user", envelope.message.content,
                    intent=intent.value, agent=agent.config.name,
                )
                await srepo.append_message(
                    sid, "assistant", response.content,
                    intent=intent.value, agent=agent.config.name,
                )
                await s.commit()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Loop] 会话持久化跳过：{e}")

        # 记录 AgentTrace（模型/Agent/意图/轮次/trace，验收7）
        try:
            from ..database.db import get_session_factory
            from ..database.models import AgentTrace
            from ..infra.context import get_trace_id

            factory = get_session_factory()
            async with factory() as s:
                s.add(AgentTrace(
                    session_id=envelope.message.thread_id or envelope.message.customer_id,
                    message_id=envelope.message.id,
                    agent=agent.config.name,
                    intent=str(intent.value) if intent else None,
                    turns=int(response.metadata.get("turns", 0)),
                    metadata_={"trace_id": get_trace_id(), "confidence": envelope.intent_confidence},
                ))
                await s.commit()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Loop] AgentTrace 写入跳过：{e}")

        return response

    async def _handle_guardrail(self, envelope: Envelope) -> Response | None:
        """护栏检查处理器。"""
        if envelope.response is None:
            return None

        result = await self.guardrail.check(envelope.response.content)
        if not result.passed:
            envelope.guardrail_flagged = True
            envelope.guardrail_reason = result.reason
            envelope.response.content = result.modified_content or result.reason
            logger.warning(f"[Loop] 护栏拦截: {result.reason}")

        return None

    # ── 公开接口 ─────────────────────────────────────────────────────────

    async def handle_message(self, message: Message) -> Response:
        """处理一条客户消息 —— 这是外部调用的主入口。

        Args:
            message: 归一化后的客户消息

        Returns:
            Response: 系统回复
        """
        logger.info(f"[Loop] 处理消息: customer={message.customer_id} platform={message.platform}")

        # 统一 Trace ID 贯穿本次请求（Router/Agent/工具/检索）
        from ..infra.context import (
            Actor,
            get_actor,
            set_actor,
            set_correlation_id,
            set_trace_id,
        )
        from ..infra.observability import new_trace_id

        trace_id = new_trace_id()
        set_trace_id(trace_id)
        set_correlation_id(trace_id)

        # 注入调用者身份（Actor）：
        #   Web 模式由 JWT 依赖注入已认证 Actor，保留不动；
        #   渠道模式无 JWT，按消息 customer_id 构造弱顾客身份（is_authenticated=False）。

        existing = get_actor()
        if existing is None or not existing.is_authenticated:
            if message.customer_id:
                set_actor(Actor(
                    user_id=f"msg:{message.customer_id}",
                    role="customer",
                    customer_id=message.customer_id,
                    is_authenticated=False,
                ))
            else:
                set_actor(None)

        response = await self.bus.dispatch(message)
        if response is None:
            return Response(
                message_id=message.id,
                content="抱歉，系统暂时无法处理您的请求，请稍后再试。",
                intent=Intent.CHITCHAT,
                agent="system",
            )
        return response

    async def handle_batch(self, messages: list[Message]) -> list[Response]:
        """批量处理消息（并行）。"""
        import asyncio
        responses = await asyncio.gather(
            *(self.handle_message(msg) for msg in messages),
            return_exceptions=True,
        )
        # 将异常转换为错误响应
        result: list[Response] = []
        for msg, resp in zip(messages, responses, strict=False):
            if isinstance(resp, Exception):
                logger.exception(f"[Loop] 批量处理消息失败: {msg.id}")
                result.append(Response(
                    message_id=msg.id,
                    content="抱歉，处理您的请求时出错，请稍后再试。",
                    intent=Intent.CHITCHAT,
                    agent="system",
                ))
            else:
                result.append(resp)
        return result

    async def start(self) -> None:
        """启动系统（初始化各组件）。"""
        logger.info("[Loop] 客服系统启动中...")
        await self.memory.initialize()
        await self.guardrail.initialize()
        for agent in self.agents.values():
            await agent.initialize()
        # 启动记忆整理器（后台任务）
        try:
            await self.consolidator.start()
        except Exception:
            logger.exception("[Loop] 记忆整理器启动失败")
        logger.info("[Loop] 客服系统启动完成 ✓")

    async def shutdown(self) -> None:
        """关闭系统。"""
        logger.info("[Loop] 客服系统关闭中...")
        try:
            await self.consolidator.stop()
        except Exception as e:
            logger.debug(f"[Loop] 记忆整理器关闭失败: {e}")
        for agent in self.agents.values():
            await agent.shutdown()
        await self.memory.close()
        logger.info("[Loop] 客服系统已关闭")
