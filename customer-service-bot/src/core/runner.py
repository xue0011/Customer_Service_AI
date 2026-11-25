"""
Agent 执行器（Runner）
────────────────────
负责 Agent 与 LLM 的对话循环 —— 接收上下文，调用 LLM，处理工具调用，
直到 Agent 生成最终回复或达到最大轮次。

这是 Agent 的"引擎"，Agent 定义"做什么"，Runner 负责"怎么跑"。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from ..config.schema import AgentContext, LLMConfig, Response
from ..tools.registry import ToolRegistry

# ─── 类型定义 ──────────────────────────────────────────────────────────────

@dataclass
class LLMMessage:
    role: str          # system / user / assistant / tool
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass
class TurnResult:
    """单轮对话结果。"""
    finish_reason: str = "stop"    # stop / tool_calls / max_turns
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    messages: list[LLMMessage] = field(default_factory=list)


# ─── LLM 客户端封装 ────────────────────────────────────────────────────────

class LLMClient:
    """统一的 LLM 客户端封装，目前支持 OpenAI 兼容接口。"""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self.config.api_key,
                base_url=self.config.api_base,
                timeout=self.config.timeout,
            )
        return self._client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """调用 LLM 聊天接口。"""
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature or self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await self.client.chat.completions.create(**kwargs)
        return response.model_dump()


# ─── Agent 执行器 ──────────────────────────────────────────────────────────

class Runner:
    """Agent 执行器 —— 管理 LLM 对话循环。

    流程：
      1. 构建初始消息列表（system prompt + 上下文 + 用户消息）
      2. 调用 LLM
      3. 如果 LLM 返回 tool_calls → 执行工具 → 将结果加入消息 → 回到步骤 2
      4. 如果 LLM 返回文本 → 对话结束，返回回复
      5. 达到 max_turns 仍未结束 → 强制生成总结
    """

    def __init__(
        self,
        llm_config: LLMConfig,
        tool_registry: ToolRegistry | None = None,
        max_turns: int = 10,
    ) -> None:
        self.llm = LLMClient(llm_config)
        self.tool_registry = tool_registry or ToolRegistry()
        self.max_turns = max_turns

    async def run(
        self,
        system_prompt: str,
        context: AgentContext,
        tools: list[str] | None = None,
    ) -> Response:
        """执行一次完整的 Agent 对话。

        Args:
            system_prompt: 系统提示词
            context: Agent 上下文（含用户消息、历史、记忆等）
            tools: 启用的工具名称列表

        Returns:
            Response: Agent 生成的回复
        """
        # 构建消息列表
        messages = self._build_messages(system_prompt, context)

        # 获取工具定义
        tool_defs = self.tool_registry.get_definitions(tools) if tools else None

        turn = 0
        final_content = ""

        while turn < self.max_turns:
            turn += 1
            logger.debug(f"[Runner] 第 {turn}/{self.max_turns} 轮对话")

            # 调用 LLM
            raw = await self.llm.chat(messages, tool_defs)
            choice = raw["choices"][0]
            finish_reason = choice.get("finish_reason", "stop")

            # 情况 1：LLM 想调用工具
            if finish_reason == "tool_calls":
                assistant_msg = choice["message"]
                tool_calls = assistant_msg.get("tool_calls", [])

                # 记录 assistant 消息
                messages.append({
                    "role": "assistant",
                    "content": assistant_msg.get("content") or "",
                    "tool_calls": tool_calls,
                })

                # 执行每个工具调用（带容错：非法 JSON / 缺字段 / 工具异常）
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    tool_name = fn.get("name", "")
                    tc_id = tc.get("id", "")
                    raw_args = fn.get("arguments", "{}")
                    try:
                        tool_args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    except json.JSONDecodeError as e:
                        logger.warning(f"[Runner] 工具 {tool_name} 参数 JSON 解析失败: {e}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": json.dumps({"success": False, "error": f"参数格式错误: {e}"}, ensure_ascii=False),
                        })
                        continue
                    if tools is not None and tool_name and tool_name not in tools:
                        tool_result = {
                            "success": False,
                            "error": f"工具 '{tool_name}' 不在当前 Agent 白名单",
                        }
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": json.dumps(tool_result, ensure_ascii=False),
                        })
                        logger.warning(f"[Runner] 白名单拒绝工具 {tool_name}")
                        continue
                    try:
                        tool_result = await self.tool_registry.execute(tool_name, **tool_args)
                    except Exception as e:  # noqa: BLE001
                        tool_result = {"success": False, "error": f"工具执行异常: {e}"}
                        logger.exception(f"[Runner] 工具 {tool_name} 执行异常")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    })
                    logger.info(f"[Runner] 工具调用: {tool_name} → {str(tool_result)[:100]}")

                continue

            # 情况 2：正常文本回复
            final_content = choice["message"].get("content", "")
            messages.append({"role": "assistant", "content": final_content})
            break

        # 达到最大轮次但未正常结束
        if not final_content:
            final_content = await self._force_summarize(messages)

        return Response(
            message_id=context.message.id,
            content=final_content,
            intent=context.message.metadata.get("intent", "chitchat"),
            agent=context.message.metadata.get("agent", "system"),
            metadata={"turns": turn},
        )

    def _build_messages(
        self, system_prompt: str, context: AgentContext
    ) -> list[dict[str, Any]]:
        """构建 LLM 消息列表。"""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]

        # 注入顾客画像
        if context.customer_profile:
            profile_text = f"当前顾客信息：\n{json.dumps(context.customer_profile, ensure_ascii=False, indent=2)}"
            messages.append({"role": "system", "content": profile_text})

        # 注入记忆
        if context.memories:
            mem_text = "相关历史记忆：\n" + "\n".join(
                f"- {m.get('content', str(m))}" for m in context.memories
            )
            messages.append({"role": "system", "content": mem_text})

        # 历史对话
        messages.extend(context.history)

        # 当前用户消息
        user_content = context.message.content
        if context.message.attachments:
            user_content += "\n[附件: " + ", ".join(context.message.attachments) + "]"

        messages.append({"role": "user", "content": user_content})

        return messages

    async def _force_summarize(self, messages: list[dict[str, Any]]) -> str:
        """当达到最大轮次时，强制 LLM 生成摘要回复。"""
        messages.append({
            "role": "user",
            "content": "请基于以上对话，用一句话总结并回复用户。",
        })
        try:
            raw = await self.llm.chat(messages, tools=None)
            return raw["choices"][0]["message"].get("content", "抱歉，处理超时，请稍后再试。")
        except Exception:
            logger.exception("[Runner] 强制总结失败")
            return "抱歉，处理超时，请稍后再试。"
