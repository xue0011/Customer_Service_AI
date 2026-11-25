"""
记忆整理器（Consolidator）
─────────────────────────
定期对记忆进行整理和压缩 —— 使用 LLM 进行：

  - 长对话总结为关键信息
  - 提取顾客偏好和习惯，更新顾客画像
  - 清理过期记忆
  - 合并重复信息

后台异步运行，不影响主消息处理流程。
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

from loguru import logger

from ..config.schema import LLMConfig, MemoryConfig
from ..core.runner import LLMClient
from .store import MemoryStore


class MemoryConsolidator:
    """记忆整理器 —— 定期整理和压缩记忆。"""

    def __init__(
        self,
        memory_store: MemoryStore,
        config: MemoryConfig,
        llm_config: LLMConfig | None = None,
    ) -> None:
        self.memory = memory_store
        self.config = config
        self.llm_client = LLMClient(llm_config) if llm_config else None
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"[Consolidator] 记忆整理已启动，间隔 {self.config.consolidation_interval}s")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[Consolidator] 记忆整理已停止")

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.config.consolidation_interval)
                await self._consolidate()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[Consolidator] 整理出错")

    async def _consolidate(self) -> None:
        logger.debug("[Consolidator] 开始整理记忆...")
        if self.llm_client:
            await self._summarize_long_threads()
            await self._extract_preferences()
        await self._cleanup_expired()

    async def summarize_thread(self, customer_id: str, thread_id: str) -> str | None:
        """使用 LLM 对长对话进行总结。"""
        history = await self.memory.get_history(customer_id, thread_id)
        if len(history) < 10:
            return None

        try:
            conversation = ""
            for entry in history:
                conversation += f"顾客: {entry.get('user_message', '')}\n"
                conversation += f"客服: {entry.get('assistant_message', '')}\n"

            messages = [
                {"role": "system", "content": "你是一个对话总结助手。请用3-5句话总结以下客服对话的关键信息，包括：顾客的核心问题、解决方案、是否已解决。只输出总结，不要额外内容。"},
                {"role": "user", "content": conversation},
            ]
            raw = await self.llm_client.chat(messages, temperature=0.3)
            summary = raw["choices"][0]["message"].get("content", "")
            logger.info(f"[Consolidator] 对话总结完成: {customer_id}/{thread_id}")
            return summary
        except Exception as e:
            logger.error(f"[Consolidator] 对话总结失败: {e}")
            return None

    async def _summarize_long_threads(self) -> None:
        """对超过20条消息的长对话进行总结。"""
        logger.debug("[Consolidator] 检查长对话...")
        try:
            customer_ids = await self.memory.get_all_customer_ids()
        except Exception:
            logger.debug("[Consolidator] 无法获取客户列表，跳过对话总结")
            return

        summarized = 0
        for cid in customer_ids:
            try:
                history = await self.memory.get_history(cid, limit=50)
                if len(history) >= 20:
                    summary = await self.summarize_thread(cid, "")
                    if summary:
                        await self.memory.save_interaction(
                            customer_id=cid,
                            thread_id="",
                            user_message="",
                            assistant_message=f"[对话总结] {summary}",
                            metadata={"type": "conversation_summary"},
                        )
                        summarized += 1
            except Exception:
                logger.exception(f"[Consolidator] 总结客户 {cid} 对话失败")
        if summarized:
            logger.info(f"[Consolidator] 总结了 {summarized} 条长对话")

    async def extract_customer_preferences(self, customer_id: str) -> dict[str, object]:
        """使用 LLM 从对话中提取顾客偏好。"""
        history = await self.memory.get_history(customer_id, limit=30)
        if not history:
            return {}

        try:
            conversation = ""
            for entry in history:
                conversation += f"顾客: {entry.get('user_message', '')}\n"

            messages = [
                {"role": "system", "content": """你是一个顾客画像分析助手。从对话中提取顾客的偏好信息，输出 JSON 格式：
{
  "preferred_categories": ["偏好的商品类别"],
  "budget_range": "价格区间",
  "preferred_colors": ["偏好的颜色"],
  "preferred_sizes": ["偏好的尺码"],
  "pain_points": ["顾客的痛点"],
  "buying_frequency": "购买频率",
  "platform_preference": "偏好的平台",
  "notes": "其他备注"
}
只输出 JSON，不要额外内容。"""},
                {"role": "user", "content": conversation},
            ]
            raw = await self.llm_client.chat(messages, temperature=0.3)
            text = raw["choices"][0]["message"].get("content", "{}")
            # 提取 JSON
            import re
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                preferences = json.loads(match.group())
                logger.info(f"[Consolidator] 偏好提取完成: {customer_id}")
                return preferences
        except Exception as e:
            logger.error(f"[Consolidator] 偏好提取失败: {e}")
        return {}

    async def _extract_preferences(self) -> None:
        """定期提取所有活跃顾客的偏好。"""
        logger.debug("[Consolidator] 提取顾客偏好...")
        try:
            customer_ids = await self.memory.get_all_customer_ids()
        except Exception:
            logger.debug("[Consolidator] 无法获取客户列表，跳过偏好提取")
            return

        extracted = 0
        for cid in customer_ids:
            try:
                prefs = await self.extract_customer_preferences(cid)
                if prefs:
                    existing = await self.memory.get_customer_profile(cid)
                    existing.update(prefs)
                    await self.memory.save_customer_profile(cid, existing)
                    extracted += 1
            except Exception:
                logger.exception(f"[Consolidator] 提取客户 {cid} 偏好失败")
        if extracted:
            logger.info(f"[Consolidator] 提取了 {extracted} 位顾客的偏好")

    async def cleanup_expired(self, days: int = 90) -> int:
        """清理过期记忆。"""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        cleaned = 0

        if self.memory.backend == "file":
            from pathlib import Path
            persist_dir = Path(self.config.persist_dir)
            for path in persist_dir.glob("*.jsonl"):
                lines = []
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        try:
                            ts = datetime.fromisoformat(entry.get("timestamp", ""))
                            if ts > cutoff:
                                lines.append(line)
                            else:
                                cleaned += 1
                        except (ValueError, TypeError):
                            lines.append(line)
                if cleaned > 0:
                    path.write_text("".join(lines), encoding="utf-8")

        logger.info(f"[Consolidator] 清理了 {cleaned} 条过期记忆")
        return cleaned
