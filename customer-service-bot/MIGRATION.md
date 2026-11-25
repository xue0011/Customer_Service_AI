# 迁移说明：Demo (v0.1) → 企业级 (v0.2 P0)

本文档记录 P0 阶段从 Demo 升级为企业级可开源部署的变更，以及破坏性变更与迁移步骤。

## 数据层：MySQL/JSON → PostgreSQL + SQLAlchemy + Alembic

- 新增 `src/database/models.py`：12 张核心表（users、refresh_tokens、sessions、messages、
  orders、order_items、refund_requests、approval_tasks、agent_traces、tool_call_logs、
  audit_logs、idempotency_keys）。
- 新增 `src/database/db.py`：异步引擎 + 连接池（生产 asyncpg，测试 aiosqlite）。
- 新增 `src/database/repositories_async.py`：异步仓储，返回字典与原 JSON 结构对齐。
- 新增 `alembic/` 与 `alembic.ini`：版本化迁移（`alembic upgrade head`）。
- 旧 `src/database/connection.py`、`repository.py`（MySQL 同步）保留为 deprecated，不再默认启用。

**迁移步骤**：
```bash
cp .env.example .env  # 填写 POSTGRES_* / JWT_SECRET / INIT_ADMIN_PASSWORD
alembic upgrade head  # 建表
python -m src.database.seed_db  # 可选：导入 data/orders 示例数据
```

## Redis：会话缓存 / 限流 / 幂等

- 新增 `src/infra/redis_client.py`：异步 Redis（测试用 fakeredis 注入）。
- 限流 `src/infra/ratelimit.py`：Redis 滑动窗口，内存降级；不再盲信 `X-Forwarded-For`。
- 幂等 `src/infra/idempotency.py`：`Idempotency-Key` 防重复提交。

## 认证授权：JWT + RBAC

- 新增 `src/auth/`：密码哈希（bcrypt）、JWT（access/refresh）、RBAC 权限矩阵、
  FastAPI 依赖（`get_current_user` 注入 `Actor` 上下文）。
- 角色：customer / agent / lead / admin。
- 初始管理员由 `INIT_ADMIN_USERNAME/PASSWORD` 在启动时创建。

## 工具安全（验收 5/6/7）

- `src/tools/base.py`：`safe_execute` 统一参数校验 / 权限校验 / 超时 / 异常处理 / 审计日志 / 高风险确认。
- `src/tools/security.py`：订单归属校验（IDOR 防护）。
- order_query / logistics_query / refund_query：查询校验调用者身份与订单归属。
- modify_order：高风险二次确认（`confirmed=true`）；修复多商品订单被截断的缺陷。
- return_apply：退货/退款接入审批 FSM（RefundRequest + ApprovalTask），金额≥阈值或检查未通过 → 人工审批。
- Runner（`src/core/runner.py`）：工具调用参数 JSON 解析容错、缺字段 `.get`、工具异常回填而非冒泡。
- Loop（`src/core/loop.py`）：每条消息注入 `Actor`（渠道模式按 `customer_id` 构造弱身份）。

## API

- 新增 `src/api/server.py`：FastAPI 企业 API（/health、/ready、/api/auth/*、/api/orders/*、
  /api/admin/approvals、/api/admin/sessions）。
- `python -m src.main --api` 启动；Docker CMD 默认 `--api`。
- legacy `src/web_server.py` 保留兼容（`--web`）。

## 基础设施

- `Dockerfile`：多阶段构建、non-root、HEALTHCHECK、启动执行 `alembic upgrade head`。
- `docker-compose.yml`：PostgreSQL（pgvector）+ Redis（含 healthcheck）+ app。
- `.github/workflows/ci.yml`：ruff 与 coverage 阻塞式、pip-audit、pip 缓存。

## 破坏性变更

1. **数据库**：默认 PostgreSQL；旧 MySQL `MYSQL_*` 环境变量不再生效，改用 `POSTGRES_*` / `DATABASE_URL`。
2. **order_query**：移除 `phone` 与 `phone 后4位` 查询（IDOR 风险）；仅支持 `order_id` / `customer_id`。
3. **return_apply**：人工审核不再写 `data/tickets/*.json`，改写入 `refund_requests` + `approval_tasks` 表，返回 `approval_task_id`（原 `ticket_id`）。
4. **工具调用**：高风险工具需 `confirmed=true`（modify_order）；`safe_execute` 返回结构为 `{success, data, error}`（不再二次包装 execute 的 dict 返回）。
5. **启动**：Docker 默认 `--api`（原 `--web`）；`--web` 仍可用。

## 兼容性保留

- Agent / Runner / MessageBus / Classifier / Guardrail / Memory / Channels 抽象未变。
- 工具层 JSON 回退保留（DB 不可用时降级读 `data/*.json`，便于本地演示）。
- legacy `web_server.py`、`database/connection.py`、`repository.py`、`security.py` 保留未删除。

## P1（v0.3）—— RAG / Router / 状态机 / 可观测

- **RAG 升级**：新增 `src/rag/`（chunker / indexer / retriever / engine / loader / repositories），`rag_documents` + `rag_embeddings` 表；文档上传/解析/切分/异步向量化/管理；混合检索（向量 + 关键词 RRF）+ Rerank + 答案引用来源（Citation）+ Metadata Filter。向量存 JSON list（兼容 SQLite 测试，应用层 cosine）；生产可启用 pgvector `Vector` 列 + ANN 索引。替代方案 Qdrant（独立服务，更高吞吐但多组件）。
- **Router Agent**：新增 `src/agents/router.py`（分类 + 置信度门限 + 转人工标记），loop 调用链 Router → 专用 Agent → ToolRegistry。
- **工具白名单**：Runner 执行工具前校验 `tool_name in tools`，售前 Agent 白名单不含退款/改单（`config/settings.py`）。
- **状态机**：新增 `src/approval/fsm.py`（退款/退货/改地址转换表 + 校验）；`RefundRequestRepository.transition` 强制 FSM；改地址走 `ApprovalTask(type=address_change)`。
- **可观测**：新增 `src/infra/observability.py`（OTel span 可选，未装降级 NoOp）；loop 生成统一 Trace ID 贯穿，写入 `agent_traces`；工具调用写 `tool_call_logs`（含 trace_id）。替代方案 Langfuse。
- **API**：RAG 文档管理（upload/list/delete）、退款 transition、改地址。
- **测试**：`tests/test_p1.py`（切分/检索/rerank/filter/引用、Router 路由、白名单拒绝、FSM 合法/非法）。

## B/C/D 修复（v0.3.1）

- **B legacy 清理**：删除 `connection.py` / `repository.py` / `seed.py`（同步 MySQL 阻塞）；`loop.py` 移除 get_db 接线（工具层已用异步仓储）；`pyproject` 移除 `mysql-connector-python`。`web_server.py` / `memory/store.py` 的延迟 import 自动回退 JSON，保持 legacy `--web` 可运行。
- **C pgvector ANN**：迁移 `0002_pgvector`（PG：`CREATE EXTENSION vector` + `embedding_vec` 列 + HNSW 索引）；`retriever._search_pg` 生产 ANN 查询路径（PG + 向量可用时走 `ORDER BY <=>`，失败回退应用层 cosine）；`indexer` 在 PG 时写入 `embedding_vec`。SQLite 测试仍用应用层 cosine，保持可测。
- **D ARQ 异步**：`tasks.py`（Worker + `rag_index_document`）；`/api/admin/rag/documents` 上传支持 `ARQ_ASYNC=1` 走 worker，否则同步处理（可测）。

> C/D 代码就绪；真实 PG/Redis 环境的端到端实测需在具备 Docker 的机器执行 `docker compose up`。

## 已知后续（P2）

- 渠道 webhook 验签、token 刷新、重试退避。
- SSE/WebSocket 流式、会话状态外部化以支持多副本。
- RAG 增量 upsert、检索评测 harness。
- `web_server.py` / `security.py` legacy 进一步迁移（当前标注 deprecated，建议生产用 `--api`）。
