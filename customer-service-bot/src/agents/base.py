"""
Agent 基类
─────────
所有客服 Agent 的抽象基类，定义了 Agent 的完整生命周期：

  initialize() → run() → [loop] → shutdown()

子类只需要实现：
  - _get_system_prompt(): 返回系统提示词
  - _get_default_tools(): 返回默认工具列表

框架会自动处理 LLM 对话循环、工具调用、记忆管理等。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from loguru import logger

from ..config.schema import AgentConfig, AgentContext, Response
from ..core.runner import Runner
from ..memory.store import MemoryStore
from ..tools.registry import ToolRegistry


class BaseAgent(ABC):
    """Agent 抽象基类。

    每个 Agent 包含：
      - config: Agent 配置（模型、工具、参数等）
      - runner: LLM 对话执行器
      - tool_registry: 工具注册表
      - memory: 记忆系统引用
    """

    def __init__(
        self,
        config: AgentConfig,
        memory: MemoryStore | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.config = config
        self.memory = memory
        self.tool_registry = tool_registry or ToolRegistry()
        self.runner = Runner(
            llm_config=config.llm,
            tool_registry=self.tool_registry,
            max_turns=config.max_turns,
        )
        self._system_prompt: str = ""
        self._initialized = False

    # ── 生命周期 ──────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """初始化 Agent：加载 prompt、注册工具。"""
        self._system_prompt = await self._load_system_prompt()
        await self._register_tools()
        self._initialized = True
        logger.info(f"[{self.config.name}] Agent 初始化完成")

    async def shutdown(self) -> None:
        """关闭 Agent，释放资源。"""
        self._initialized = False
        logger.info(f"[{self.config.name}] Agent 已关闭")

    # ── 核心接口 ──────────────────────────────────────────────────────────

    async def run(self, context: AgentContext) -> Response:
        """执行 Agent —— 对外暴露的主入口。

        Args:
            context: 完整的 Agent 上下文

        Returns:
            Response: Agent 生成的回复
        """
        if not self._initialized:
            await self.initialize()

        logger.info(f"[{self.config.name}] 开始处理消息 {context.message.id}")

        # 预处理：子类可覆写
        context = await self._preprocess(context)

        # 执行 LLM 对话
        response = await self.runner.run(
            system_prompt=self._system_prompt,
            context=context,
            tools=self._get_default_tools(),
        )

        # 后处理：子类可覆写
        response = await self._postprocess(response, context)

        logger.info(f"[{self.config.name}] 回复生成完成")
        return response

    # ── 子类需覆写的方法 ──────────────────────────────────────────────────

    @abstractmethod
    async def _get_system_prompt(self) -> str:
        """返回系统提示词。子类必须实现。"""
        ...

    @abstractmethod
    def _get_default_tools(self) -> list[str]:
        """返回默认启用的工具名称列表。子类必须实现。"""
        ...

    # ── 可覆写的钩子方法 ──────────────────────────────────────────────────

    async def _preprocess(self, context: AgentContext) -> AgentContext:
        """预处理上下文（消息增强、敏感信息过滤等）。"""
        return context

    async def _postprocess(self, response: Response, context: AgentContext) -> Response:
        """后处理回复（格式调整、添加签名等）。"""
        return response

    # ── 内部方法 ──────────────────────────────────────────────────────────

    async def _load_system_prompt(self) -> str:
        """加载系统提示词。"""
        # 优先从子类方法获取
        custom = await self._get_system_prompt()
        if custom:
            return custom

        # 否则从文件加载
        if self.config.system_prompt_path:
            path = Path(self.config.system_prompt_path)
            if path.exists():
                return path.read_text(encoding="utf-8")
            logger.warning(f"[{self.config.name}] Prompt 文件不存在: {path}")

        return "你是一个专业的客服助手。"

    async def _register_tools(self) -> None:
        """注册 Agent 所需的工具。"""
        for tool_name in self.config.tools:
            if tool_name not in self.tool_registry:
                logger.warning(f"[{self.config.name}] 工具 '{tool_name}' 未在注册表中找到")
