"""Pydantic 配置模型 —— 定义整个系统的配置结构。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, SecretStr

# ─── 意图分类 ──────────────────────────────────────────────────────────────

class Intent(str, Enum):
    PRESALES = "presales"
    AFTERSALES = "aftersales"
    CHITCHAT = "chitchat"


class Platform(str, Enum):
    TAOBAO = "taobao"
    JD = "jd"
    PINDUODUO = "pinduoduo"
    DEWU = "dewu"


# ─── 消息模型 ──────────────────────────────────────────────────────────────

class Message(BaseModel):
    """统一消息模型 —— 所有渠道消息归一化为此结构。"""

    id: str
    platform: Platform
    channel: str = ""          # 渠道子类型，如 "taobao"
    customer_id: str
    customer_name: str = ""
    content: str
    content_type: str = "text"  # text / image / voice / video
    attachments: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    thread_id: str = ""        # 会话 ID，用于记忆关联


class Response(BaseModel):
    """统一回复模型。"""

    message_id: str            # 对应原始消息 ID
    content: str
    intent: Intent
    agent: str                # 处理该消息的 Agent 名称
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentContext(BaseModel):
    """Agent 执行时的上下文。"""

    message: Message
    history: list[dict[str, str]] = Field(default_factory=list)
    memories: list[dict[str, Any]] = Field(default_factory=list)
    customer_profile: dict[str, Any] = Field(default_factory=dict)
    shop_config: dict[str, Any] = Field(default_factory=dict)


# ─── LLM 配置 ──────────────────────────────────────────────────────────────

class LLMConfig(BaseModel):
    provider: str = "openai"               # openai / anthropic / local
    model: str = "qwen3.6-plus"
    api_key: SecretStr = Field(default=SecretStr(""))
    api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout: float = 30.0

    def api_key_plain(self) -> str:
        return self.api_key.get_secret_value()


# ─── Agent 配置 ─────────────────────────────────────────────────────────────

class AgentConfig(BaseModel):
    name: str
    description: str = ""
    system_prompt_path: str = ""            # 相对于 prompts/ 的路径
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tools: list[str] = Field(default_factory=list)   # 工具名称列表
    max_turns: int = 10                     # Agent 最大对话轮次
    temperature: float = 0.7


# ─── 记忆配置 ──────────────────────────────────────────────────────────────

class MemoryConfig(BaseModel):
    backend: str = "chroma"                 # chroma / redis / file
    persist_dir: str = "./data/memory"
    max_context_messages: int = 20
    consolidation_interval: int = 300       # 记忆整理间隔（秒）


# ─── 护栏配置 ──────────────────────────────────────────────────────────────

class GuardrailRule(BaseModel):
    """单条护栏规则。"""

    name: str
    type: str = "keyword"                   # keyword / regex / llm
    pattern: str = ""                       # 关键词或正则
    action: str = "block"                   # block / warn / rewrite
    message: str = "此回复包含不合规内容，已被拦截。"


class GuardrailConfig(BaseModel):
    enabled: bool = True
    rules: list[GuardrailRule] = Field(default_factory=list)
    llm_check_enabled: bool = True
    llm: LLMConfig = Field(default_factory=LLMConfig)


# ─── 退货政策配置 ──────────────────────────────────────────────────────────

class ReturnPolicyConfig(BaseModel):
    """退货政策配置 —— 集中管理退货规则。"""

    allowed_window_days: int = 7          # 无理由退货窗口
    min_amount_auto: float = 200.0        # 低于此金额自动判断，高于则人工审核
    refund_processing_days: int = 5       # 处理退款的工作日
    conditions: list[str] = Field(
        default_factory=lambda: [
            "商品完好，不影响二次销售",
            "吊牌、标签完整",
            "赠品需一并退回",
            "非定制/生鲜/易耗品",
        ]
    )
    return_address: str = "浙江省杭州市余杭区仓前街道XX路XX号 退货组收"
    return_phone: str = "0571-8888XXXX"


# ─── 渠道配置 ──────────────────────────────────────────────────────────────

class ChannelConfig(BaseModel):
    type: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


# ─── 数据库配置（PostgreSQL）──────────────────────────────────────────────

class DatabaseConfig(BaseModel):
    """PostgreSQL 数据库配置。

    生产用 asyncpg，测试可用 sqlite+aiosqlite。DATABASE_URL 优先于散字段。
    """

    url: str = ""                            # 例 postgresql+asyncpg://user:pass@host:port/db
    host: str = "localhost"
    port: int = 5432
    user: str = "csbot"
    password: SecretStr = Field(default=SecretStr(""))
    database: str = "customer_service"
    pool_size: int = 10
    max_overflow: int = 20
    pool_recycle: int = 3600
    echo: bool = False

    def resolved_url(self) -> str:
        """返回可用于 SQLAlchemy async 引擎的 URL。"""
        if self.url:
            u = self.url
            # 兼容用户写 postgresql:// 或 postgres://
            if u.startswith("postgresql://") or u.startswith("postgres://"):
                u = u.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
                    "postgres://", "postgresql+asyncpg://", 1
                )
            return u
        pw = self.password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.user}:{pw}@{self.host}:{self.port}/{self.database}"
        )

    def is_sqlite(self) -> bool:
        return self.resolved_url().startswith("sqlite")


# ─── Redis 配置 ─────────────────────────────────────────────────────────────

class RedisConfig(BaseModel):
    """Redis 配置（会话缓存、限流、幂等）。"""

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: SecretStr = Field(default=SecretStr(""))
    key_prefix: str = "csbot:"

    def url(self) -> str:
        pw = self.password.get_secret_value()
        auth = f":{pw}@" if pw else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


# ─── 认证授权配置 ──────────────────────────────────────────────────────────

class JWTConfig(BaseModel):
    secret: SecretStr = Field(default=SecretStr(""))
    algorithm: str = "HS256"
    access_expire_minutes: int = 60
    refresh_expire_days: int = 7


class RBACConfig(BaseModel):
    """RBAC 与初始管理员。"""

    default_role: str = "customer"
    superuser_username: str = "admin"
    superuser_password: SecretStr = Field(default=SecretStr(""))


# ─── 审批配置 ──────────────────────────────────────────────────────────────

class ApprovalConfig(BaseModel):
    """高风险操作审批（退货/退款/改单）。"""

    auto_review_threshold: float = 200.0
    allowed_window_days: int = 7
    sla_hours: int = 24                       # 人工审批 SLA，超时升级


# ─── 审计日志配置 ──────────────────────────────────────────────────────────

class AuditConfig(BaseModel):
    enabled: bool = True
    log_file: str = "./logs/audit.jsonl"


# ─── 总配置 ────────────────────────────────────────────────────────────────

class AppConfig(BaseModel):
    """应用总配置 —— 所有子系统的配置聚合。"""

    shop_name: str = "默认店铺"
    shop_id: str = "default"

    presales_agent: AgentConfig = Field(default_factory=AgentConfig)
    aftersales_agent: AgentConfig = Field(default_factory=AgentConfig)

    classifier: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    guardrail: GuardrailConfig = Field(default_factory=GuardrailConfig)
    return_policy: ReturnPolicyConfig = Field(default_factory=ReturnPolicyConfig)

    channels: list[ChannelConfig] = Field(default_factory=list)

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    jwt: JWTConfig = Field(default_factory=JWTConfig)
    rbac: RBACConfig = Field(default_factory=RBACConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)

    data_dir: str = "./data"
    prompts_dir: str = "./prompts"

    app_env: str = "production"              # development / production
