"""
工具注册表（Tool Registry）
──────────────────────────
全局工具注册中心 —— 管理所有可用工具，提供查找、注册、获取定义等功能。

使用方式：
    registry = ToolRegistry()
    registry.register(OrderQueryTool())
    registry.register(KnowledgeBaseTool())

    # 获取工具定义（给 LLM）
    definitions = registry.get_definitions(["order_query", "knowledge_base"])

    # 执行工具
    result = await registry.execute("order_query", order_id="12345")
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from .base import BaseTool


class ToolRegistry:
    """工具注册表 —— 单例模式管理所有工具。"""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    # ── 注册与注销 ──────────────────────────────────────────────────────

    def register(self, tool: BaseTool) -> None:
        """注册一个工具。"""
        if tool.name in self._tools:
            logger.warning(f"[ToolRegistry] 工具 '{tool.name}' 已存在，将被覆盖")
        self._tools[tool.name] = tool
        logger.debug(f"[ToolRegistry] 注册工具: {tool.name}")

    def register_many(self, tools: list[BaseTool]) -> None:
        """批量注册工具。"""
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> None:
        """注销工具。"""
        self._tools.pop(name, None)
        logger.debug(f"[ToolRegistry] 注销工具: {name}")

    # ── 查询 ────────────────────────────────────────────────────────────

    def get(self, name: str) -> BaseTool | None:
        """获取工具实例。"""
        return self._tools.get(name)

    def list(self) -> list[str]:
        """列出所有工具名称。"""
        return list(self._tools.keys())

    def get_definitions(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        """获取工具定义列表（OpenAI function calling 格式）。

        Args:
            names: 需要的工具名称列表，None 表示全部
        """
        if names is None:
            names = list(self._tools.keys())

        definitions = []
        for name in names:
            tool = self._tools.get(name)
            if tool:
                definitions.append(tool.get_definition())
            else:
                logger.warning(f"[ToolRegistry] 请求的工具 '{name}' 未注册")
        return definitions

    # ── 执行 ────────────────────────────────────────────────────────────

    async def execute(self, tool_name: str, **kwargs: Any) -> dict[str, Any]:
        """执行一个工具。

        Args:
            tool_name: 工具名称
            **kwargs: 工具参数

        Returns:
            执行结果字典
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return {"success": False, "error": f"工具 '{tool_name}' 不存在"}

        logger.info(f"[ToolRegistry] 执行工具: {tool_name}({kwargs})")
        return await tool.safe_execute(**kwargs)

    # ── 特殊方法 ────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        return f"<ToolRegistry({len(self._tools)} tools: {list(self._tools.keys())})>"
