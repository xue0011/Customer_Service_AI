"""运行配置：全部来自环境变量，缺省值保证「无 API Key 也能跑离线规则模式」。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

# customer-service-bot/
BASE_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = Path(__file__).resolve().parent / "skills"
DATA_DIR = BASE_DIR / "data"
MCP_CONFIG = BASE_DIR / "mcp_servers.json"


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


class Settings(BaseModel):
    """LLM / 路由 / 审批阈值配置。"""

    model: str = Field(default_factory=lambda: _env("OPENAI_MODEL", "gpt-4o-mini"))
    api_key: str = Field(default_factory=lambda: _env("OPENAI_API_KEY", ""))
    base_url: str | None = Field(default_factory=lambda: os.getenv("OPENAI_API_BASE") or None)
    temperature: float = Field(default_factory=lambda: float(_env("LLM_TEMPERATURE", "0.2")))

    # 意图置信度低于该值 → 转人工
    confidence_threshold: float = Field(
        default_factory=lambda: float(_env("ROUTER_CONFIDENCE_THRESHOLD", "0.55"))
    )
    # 退货金额超过该值 → 必须人工审批（LangGraph interrupt）
    return_approve_threshold: float = Field(
        default_factory=lambda: float(_env("RETURN_APPROVE_THRESHOLD", "200"))
    )
    max_message_chars: int = 2000

    @property
    def llm_enabled(self) -> bool:
        return bool(self.api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
