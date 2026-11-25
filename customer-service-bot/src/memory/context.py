"""
上下文构建器（Context Builder）
──────────────────────────────
负责在 Agent 执行前自动构建完整的上下文，包括：

  - 加载对话历史
  - 检索相关记忆
  - 加载顾客画像
  - 拼接为 AgentContext
"""

from __future__ import annotations

from ..config.schema import AgentContext, Message
from .store import MemoryStore


class ContextBuilder:
    """上下文构建器 —— 自动加载相关记忆和上下文。"""

    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory = memory_store

    async def build(
        self,
        message: Message,
        customer_id: str,
        thread_id: str | None = None,
        max_history: int = 20,
        max_memories: int = 10,
    ) -> AgentContext:
        """构建完整的 Agent 上下文。

        Args:
            message: 当前用户消息
            customer_id: 顾客 ID
            thread_id: 会话 ID
            max_history: 最大历史消息数
            max_memories: 最大记忆条数

        Returns:
            AgentContext: 完整的执行上下文
        """
        tid = thread_id or message.thread_id

        # 并行加载各项上下文
        history = await self.memory.get_history(customer_id, tid, max_history)
        memories = await self.memory.search(message.content, customer_id, max_memories)
        customer_profile = await self.memory.get_customer_profile(customer_id)

        # 构建 LLM 格式的历史消息
        history_messages = []
        for entry in history:
            history_messages.append({
                "role": "user",
                "content": entry.get("user_message", ""),
            })
            history_messages.append({
                "role": "assistant",
                "content": entry.get("assistant_message", ""),
            })

        return AgentContext(
            message=message,
            history=history_messages,
            memories=memories,
            customer_profile=customer_profile,
            shop_config={},  # 可从全局配置注入
        )
