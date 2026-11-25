<img width="652" height="670" alt="image" src="https://github.com/user-attachments/assets/35555cf4-d62a-4a7f-b6d2-5c636b143a15" /># Customer Service Bot

> 企业级多 Agent 智能客服系统 —— 面向电商售前/售后场景，支持多 Agent 路由、RAG 知识库、订单/物流/退款/退货工具调用，具备 JWT 认证、RBAC、人工审批、幂等、限流、审计日志，基于 PostgreSQL + Redis + Docker Compose。
> <img width="941" height="517" alt="image" src="https://github.com/user-attachments/assets/37f2bf13-a843-4308-a4c3-a2f3906d7915" />




## 特性

- **多 Agent 编排**：消息总线 + 意图分类 → 售前/售后 Agent，工具调用循环（OpenAI 兼容）。
- **数据持久化**：PostgreSQL + SQLAlchemy 2.0 异步 + Alembic 迁移；本地开发可用 SQLite。
- **认证授权**：JWT（access/refresh）+ RBAC（customer/agent/lead/admin）。
- **工具安全**：所有订单/物流/退款/退货工具校验调用者身份与订单归属（防 IDOR）；高风险操作（改单/退货）经二次确认或人工审批。
- **横切能力**：Redis 分布式限流、幂等键、append-only 审计日志、工具调用日志。
- **可观测**：`/health` `/ready` 健康检查、结构化审计文件、Agent Trace 与 ToolCallLog 表。
- **可复用**：保留原有 Agent/工具/渠道抽象，增量增强而非重写。

## LangGraph / LangChain / Skill / MCP 重构版

除原有 `src/` 实现外，仓库新增 `langgraph_app/`：业务流不变（输入守卫 → 意图路由 → 领域 Agent → 风控 → 输出守卫），编排换成 **LangGraph 状态图**，工具换成 **LangChain Tool**，领域知识换成 **SKILL.md**，设备控制换成 **MCP**。两套实现并行、互不依赖，`src/` 不受影响。

### 核心变化

- **路由是图上的节点**：`route_node` 用 LLM 结构化输出判意图，置信度低于 `0.55` 直接转人工，不「蒙一个」。
- **审批是图的中断**：退货金额超过 `200` 元时 `risk_gate` 触发 `interrupt()`，`POST /chat/{thread_id}/approve` 恢复执行。
- **技能是文件**：`langgraph_app/skills/*/SKILL.md`，第一级只把 `name + description` 注入 prompt，需要时 `load_skill(name)` 取全文——新增技能不用改代码。
- **设备走 MCP**：`device` 意图通过 `mcp_servers.json` 连接 MiDeviceController 的 `mcp_server.py`（列设备 / 查状态 / 开关 / 亮度 / 色温 / 模式 / 档位）。
- **输出守卫**：命中「保证全额赔付」「100%退款」等禁用话术时替换回复，并要求人工复核。
- **无 Key 可跑**：未配置 `OPENAI_API_KEY` 时自动进入离线规则模式（正则解析订单号 + 直接调工具），方便演示与 CI。

### 快速体验

```bash
pip install -r requirements-langgraph.txt
python -m langgraph_app      # http://127.0.0.1:8010/docs

curl -s http://127.0.0.1:8010/chat -H 'Content-Type: application/json' \
  -d '{"text":"ORD-20251102-002 申请退货","customer_id":"cust_001","thread_id":"t1"}'
```

### 目录

```
langgraph_app/
├── graph.py            # 图装配：input_guard → router → 领域 Agent → risk_gate → approval → output_guard
├── nodes.py            # 各节点实现
├── state.py            # AgentState（messages / intent / confidence / pending_action ...）
├── tools.py            # 订单、物流、退款、退货、知识库、技能加载（LangChain @tool）
├── skill_registry.py   # SKILL.md 解析 + 渐进式披露
├── guardrails.py       # 输入注入检测、PII 脱敏、输出合规
├── llm.py              # 模型构建（无 Key 返回 None）
├── api.py              # FastAPI
├── mcp_servers.json    # MCP 服务器清单
└── skills/             # presales / aftersales / return-policy / device-control
```

架构图、接口清单、设计取舍详见 [docs/LANGGRAPH.md](docs/LANGGRAPH.md)。

## 架构概览

```
渠道(淘宝/京东/拼多多/得物/Web) → MessageBus(含输入护栏) → Classifier
   → Agent(presales/aftersales) → Runner(tool-calling) → Output Guardrail → 回复
        │                                            │
        └── 工具层(order/refund/logistics/modify/return) ── 归属校验 ── 审批 FSM
                             │
   PostgreSQL(SQLAlchemy) ── Redis(缓存/限流/幂等) ── 审计日志(DB+文件)

横切：JWT+RBAC · Idempotency · RateLimit · Audit · Observability
```

## 核心组件

| 组件 | 路径 | 职责 |
|------|------|------|
| **API** | `src/api/` | FastAPI 企业 API（认证/审批/订单/健康检查） |
| **Auth** | `src/auth/` | JWT、RBAC、密码哈希、FastAPI 依赖 |
| **Infra** | `src/infra/` | 请求上下文、Redis、限流、幂等、审计 |
| **Database** | `src/database/` | SQLAlchemy 模型、异步仓储、Alembic 迁移 |
| **Core** | `src/core/` | 消息总线、主循环、Agent 执行器（Runner） |
| **Agents** | `src/agents/` | 售前/售后 Agent |
| **Tools** | `src/tools/` | 工具基类 + 订单/退款/物流/RAG 工具（含安全层） |
| **Classifier** | `src/classifier/` | 意图分类 |
| **Guardrail** | `src/guardrail/` | 回复护栏 |
| **Memory** | `src/memory/` | 对话历史、顾客画像 |
| **Channels** | `src/channels/` | 多平台渠道适配 |

## 快速开始

### Docker Compose（推荐）

```bash
cp .env.example .env
# 编辑 .env：设置 JWT_SECRET / INIT_ADMIN_PASSWORD / OPENAI_API_KEY / POSTGRES_PASSWORD
docker compose up --build
# 容器启动时自动执行 alembic upgrade head 建表 + 创建管理员
```

服务：API `http://localhost:8000`、PostgreSQL `:5432`、Redis `:6379`。

### 本地开发

```bash
pip install -e ".[dev]"
cp .env.example .env
# 测试可不依赖真实 PG/Redis（SQLite + fakeredis）
pytest tests/ -v
```

### 运行模式

```bash
python -m src.main --api --port 8000   # 企业 API（JWT/RBAC/审批/健康检查）
python -m src.main --web --port 8000  # legacy 聊天 Web 界面
python -m src.main --demo             # 演示模式
python -m src.main                   # 渠道监听模式
```

## API 一览

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/health` | 无 | 存活探针 |
| GET | `/ready` | 无 | 就绪探针（DB/Redis） |
| POST | `/api/auth/login` | 无 | 登录获取 JWT |
| POST | `/api/auth/refresh` | refresh token | 刷新 access |
| GET | `/api/auth/me` | JWT | 当前用户 |
| GET | `/api/orders/{id}` | JWT | 查询订单（归属校验） |
| GET | `/api/admin/approvals` | agent+ | 待审批任务列表 |
| POST | `/api/admin/approvals/{id}/resolve` | agent+ | 通过/驳回审批 |
| POST | `/api/admin/sessions/{id}/takeover` | agent+ | 会话转人工 |
| POST | `/api/admin/rag/documents` | lead+ | 上传知识库文档（切分+向量化） |
| GET | `/api/admin/rag/documents` | agent+ | 文档列表 |
| DELETE | `/api/admin/rag/documents/{id}` | lead+ | 删除文档 |
| POST | `/api/admin/refunds/{id}/transition` | agent+ | 退款状态机转换 |
| POST | `/api/admin/address-changes` | agent+ | 改地址审批 |

## 测试

```bash
pytest tests/ -v --cov=src
```

测试覆盖：数据层（ORM/仓储/乐观锁）、认证（密码/JWT/RBAC/登录）、限流、幂等、工具安全（归属校验/二次确认/审批 FSM/幂等/审计）、API（登录/订单/审批/健康检查）。

## 环境变量

见 `.env.example`。关键项：

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | PG 连接；测试用 `sqlite+aiosqlite://` |
| `POSTGRES_*` | PostgreSQL 凭据 |
| `REDIS_*` | Redis（限流/幂等/缓存） |
| `JWT_SECRET` | JWT 签名密钥（生产必设） |
| `INIT_ADMIN_USERNAME/PASSWORD` | 初始管理员 |
| `OPENAI_API_KEY` | LLM 嵌入密钥 |
| `RETURN_AUTO_REVIEW_THRESHOLD` | 退货自动审核金额阈值 |

## P1 架构：Router 链 / 向量检索 / 状态机 / 可观测

- **Router Agent → 专用 Agent → ToolRegistry**：`RouterAgent`（分类 + 置信度门限 + 转人工标记）路由到售前/售后 Agent；Agent 工具白名单在 Runner 强制校验（**售前 Agent 无法调用退款/改单工具**）。
- **RAG**：文档上传/切分（递归字符 + 重叠）/向量化/管理（`rag_documents` + `rag_embeddings` 表）；向量持久化于 PG（JSON list，应用层 cosine；生产可启用 pgvector ANN 索引）；**混合检索**（向量 + 关键词 RRF 融合）+ **Rerank** + **答案引用来源**（Citation）+ **Metadata Filter**。
- **状态机**：退款/退货 `submitted→under_review→approved→return_received→refunded→closed`；改地址走 `ApprovalTask(type=address_change)`；非法转换由 `approval.fsm` 拒绝。
- **可观测**：统一 Trace ID 贯穿 Router/Agent/检索/工具/审批，写入 `agent_traces`/`tool_call_logs`；OpenTelemetry span 可选（未装降级 NoOp）。替代方案 Langfuse。

### 示例演示流程

1. 上传知识库文档 → `POST /api/admin/rag/documents`（自动切分 + 向量化）
2. 顾客消息 → Router 分类 → 售前/售后 Agent → 工具调用（白名单校验）
3. 退货 → `return_apply` 创建退款申请（FSM）→ 审批 → `POST /api/admin/refunds/{id}/transition`
4. 全程 Trace ID 可在 `agent_traces` / `tool_call_logs` 追溯定位

## 扩展指南

新增工具（自动获得参数校验/权限/超时/审计/确认）：

```python
from src.tools.base import BaseTool

class MyTool(BaseTool):
    required_permission = "order:read:own"  # RBAC 权限
    high_risk = False                        # 高风险则需确认或审批
    require_confirmation = False

    @property
    def name(self): return "my_tool"
    @property
    def description(self): return "..."
    @property
    def parameters(self): return {"type":"object","properties":{...},"required":[...]}
    async def execute(self, **kwargs):
        from src.tools.security import check_order_ownership
        # 查询资源后校验归属
        return {"success": True, "data": {...}}
```

新增 Agent / 渠道见原指南（`BaseAgent` / `ChannelAdapter` 抽象未变）。

## 目录结构

```
customer-service-bot/
├── src/
│   ├── main.py                 # 入口（--api/--web/--demo）
│   ├── api/                    # 企业 API（FastAPI）
│   ├── auth/                   # JWT + RBAC
│   ├── infra/                  # 上下文/Redis/限流/幂等/审计
│   ├── database/               # ORM + 异步仓储 + Alembic
│   ├── core/                   # 总线/主循环/Runner
│   ├── agents/                 # 售前/售后 Agent
│   ├── tools/                  # 工具（含安全层）
│   ├── classifier/  guardrail/  memory/  channels/  config/
├── alembic/                    # 数据库迁移
├── prompts/  data/  tests/  templates/  static/
├── docker-compose.yml  Dockerfile  pyproject.toml
└── MIGRATION.md                # 从 Demo 升级的变更说明
```

## 部署拓扑（Docker Compose）

```
app(API:8000) ──► PostgreSQL(pgvector:5432)
              ──► Redis(6379)
worker(ARQ)   ──► Redis/PG（异步向量化等长任务）
prometheus(9090) ──► app:/metrics
grafana(3000) ──► prometheus
```

一键启动：`docker compose up --build`。健康检查：`GET /health`、`GET /ready`。
演示：`BASE=http://localhost:8000 ADMIN_PASSWORD=... ./scripts/api_demo.sh`，或浏览器打开 `static/demo.html`。
示例数据：`python -m src.database.seed_db`（商品/订单/物流/退款 + 演示用户）。

## 更多文档

- [迁移说明](MIGRATION.md)
- [贡献指南](CONTRIBUTING.md) · [行为准则](CODE_OF_CONDUCT.md) · [安全策略](SECURITY.md)
- [项目亮点 / 简历 / 面试稿](docs/HIGHLIGHTS.md)
- [发布检查清单](CHECKLIST.md)

## 许可证

MIT
