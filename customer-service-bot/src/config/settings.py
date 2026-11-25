"""配置加载器 —— 从 JSON 文件与环境变量加载配置。

优先级：配置文件 > 环境变量 > 默认值
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import SecretStr

from .schema import (
    AgentConfig,
    AppConfig,
    ApprovalConfig,
    AuditConfig,
    ChannelConfig,
    DatabaseConfig,
    GuardrailConfig,
    GuardrailRule,
    JWTConfig,
    LLMConfig,
    MemoryConfig,
    RBACConfig,
    RedisConfig,
    ReturnPolicyConfig,
)


def _load_env_llm(prefix: str = "") -> LLMConfig:
    """从环境变量加载 LLM 配置。"""
    return LLMConfig(
        provider=os.getenv(f"{prefix}LLM_PROVIDER", "openai"),
        model=os.getenv(f"{prefix}LLM_MODEL", os.getenv("LLM_MODEL", "qwen3.6-plus")),
        api_key=SecretStr(
            os.getenv(f"{prefix}LLM_API_KEY", os.getenv("OPENAI_API_KEY", ""))
        ),
        api_base=os.getenv(
            f"{prefix}LLM_API_BASE",
            os.getenv("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ),
        temperature=float(os.getenv(f"{prefix}LLM_TEMPERATURE", "0.7")),
        max_tokens=int(os.getenv(f"{prefix}LLM_MAX_TOKENS", "2048")),
    )


def _load_database_config() -> DatabaseConfig:
    """从环境变量加载 PostgreSQL 配置。DATABASE_URL 优先。"""
    url = os.getenv("DATABASE_URL", "")
    pw = os.getenv("POSTGRES_PASSWORD", "")
    return DatabaseConfig(
        url=url,
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "csbot"),
        password=SecretStr(pw),
        database=os.getenv("POSTGRES_DB", "customer_service"),
        pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "3600")),
    )


def _load_redis_config() -> RedisConfig:
    return RedisConfig(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        password=SecretStr(os.getenv("REDIS_PASSWORD", "")),
    )


def _load_jwt_config() -> JWTConfig:
    return JWTConfig(
        secret=SecretStr(os.getenv("JWT_SECRET", "")),
        algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        access_expire_minutes=int(os.getenv("JWT_ACCESS_EXPIRE_MINUTES", "60")),
        refresh_expire_days=int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", "7")),
    )


def _load_rbac_config() -> RBACConfig:
    return RBACConfig(
        default_role="customer",
        superuser_username=os.getenv("INIT_ADMIN_USERNAME", "admin"),
        superuser_password=SecretStr(os.getenv("INIT_ADMIN_PASSWORD", "")),
    )


def _load_approval_config() -> ApprovalConfig:
    return ApprovalConfig(
        auto_review_threshold=float(os.getenv("RETURN_AUTO_REVIEW_THRESHOLD", "200")),
        allowed_window_days=int(os.getenv("RETURN_ALLOWED_WINDOW_DAYS", "7")),
        sla_hours=int(os.getenv("APPROVAL_SLA_HOURS", "24")),
    )


def load_config(config_path: str | None = None) -> AppConfig:
    """加载应用配置。

    优先级：配置文件 > 环境变量 > 默认值
    """
    load_dotenv()

    # 尝试从 JSON 文件加载
    config_data: dict[str, Any] = {}
    if config_path and Path(config_path).exists():
        with open(config_path, encoding="utf-8") as f:
            config_data = json.load(f)

    # 构建默认配置（可由环境变量覆盖）
    presales_llm = _load_env_llm("PRESALES_")
    aftersales_llm = _load_env_llm("AFTERSALES_")
    classifier_llm = _load_env_llm("CLASSIFIER_")

    default_config = AppConfig(
        shop_name=os.getenv("SHOP_NAME", "默认店铺"),
        shop_id=os.getenv("SHOP_ID", "default"),
        app_env=os.getenv("APP_ENV", "production"),
        presales_agent=AgentConfig(
            name="presales",
            description="售前客服 Agent，负责产品咨询、价格查询、推荐等",
            system_prompt_path="system/presales.md",
            llm=presales_llm,
            tools=["knowledge_base", "rag_search", "order_query"],
            max_turns=10,
        ),
        aftersales_agent=AgentConfig(
            name="aftersales",
            description="售后客服 Agent，负责订单查询、退换货、投诉处理等",
            system_prompt_path="system/aftersales.md",
            llm=aftersales_llm,
            tools=["order_query", "logistics_query", "refund_query", "modify_order", "return_apply", "knowledge_base"],
            max_turns=10,
        ),
        classifier=classifier_llm,
        memory=MemoryConfig(
            backend=os.getenv("MEMORY_BACKEND", "chroma"),
            persist_dir=os.getenv("MEMORY_DIR", "./data/memory"),
            max_context_messages=int(os.getenv("MEMORY_MAX_CONTEXT", "20")),
        ),
        guardrail=GuardrailConfig(
            enabled=True,
            rules=[
                GuardrailRule(
                    name="no_politics",
                    type="keyword",
                    pattern="政治,敏感,反动",
                    action="block",
                    message="涉及敏感话题，已拦截。",
                ),
                GuardrailRule(
                    name="no_competitor",
                    type="keyword",
                    pattern="去别的店,别家便宜",
                    action="warn",
                    message="请注意不要引导顾客离开本店。",
                ),
            ],
            llm_check_enabled=True,
            llm=_load_env_llm("GUARDRAIL_"),
        ),
        return_policy=ReturnPolicyConfig(
            allowed_window_days=int(os.getenv("RETURN_ALLOWED_WINDOW_DAYS", "7")),
            min_amount_auto=float(os.getenv("RETURN_AUTO_REVIEW_THRESHOLD", "200")),
            refund_processing_days=5,
        ),
        channels=[
            ChannelConfig(type="taobao", enabled=True, config={"app_key": "", "app_secret": "", "session_key": ""}),
            ChannelConfig(type="pinduoduo", enabled=True, config={"client_id": "", "client_secret": ""}),
            ChannelConfig(type="jd", enabled=True, config={"app_key": "", "app_secret": "", "access_token": ""}),
            ChannelConfig(type="dewu", enabled=True, config={"app_key": "", "app_secret": ""}),
        ],
        database=_load_database_config(),
        redis=_load_redis_config(),
        jwt=_load_jwt_config(),
        rbac=_load_rbac_config(),
        approval=_load_approval_config(),
        audit=AuditConfig(
            enabled=os.getenv("AUDIT_ENABLED", "true").lower() == "true",
            log_file=os.getenv("AUDIT_LOG_FILE", "./logs/audit.jsonl"),
        ),
    )

    # 用配置文件覆盖默认值（顶层浅合并）
    if config_data:
        merged = {**default_config.model_dump(), **config_data}
        default_config = AppConfig(**merged)

    return default_config


# ── 全局配置单例 ─────────────────────────────────────────────────────────────

_config: AppConfig | None = None


def get_config(config_path: str | None = None) -> AppConfig:
    """获取全局配置单例。"""
    global _config
    if _config is None:
        _config = load_config(config_path)
    return _config


def reset_config() -> None:
    """重置全局配置（测试用）。"""
    global _config
    _config = None
