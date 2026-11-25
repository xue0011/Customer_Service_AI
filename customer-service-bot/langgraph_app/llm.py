"""LLM 工厂：有 Key 用 ChatOpenAI，没有 Key 返回 None → 上层走离线规则。"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel

from .config import get_settings

logger = logging.getLogger(__name__)

_llm: BaseChatModel | None = None
_checked = False


def build_llm() -> BaseChatModel | None:
    """进程内单例。OpenAI 兼容网关通过 OPENAI_API_BASE 指定。"""
    global _llm, _checked
    if _checked:
        return _llm
    _checked = True
    settings = get_settings()
    if not settings.llm_enabled:
        logger.warning("[llm] 未设置 OPENAI_API_KEY，进入离线规则模式")
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:  # 依赖没装时不阻断 demo
        logger.warning("[llm] 未安装 langchain-openai，进入离线规则模式")
        return None
    _llm = ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=settings.temperature,
        timeout=60,
        max_retries=1,
    )
    return _llm
