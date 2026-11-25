# 项目亮点 / 简历描述 / 面试讲解稿

## 项目亮点

- **多 Agent 编排**：Router Agent（分类 + 置信度门限 + 转人工标记）→ 专用 Agent → ToolRegistry；工具白名单在 Runner 强制校验（售前无法发起退款/改单）。
- **企业级安全**：JWT + RBAC、订单归属校验防 IDOR、改单二次确认、退款/退货/改地址人工审批 FSM、Redis 分布式限流与幂等、append-only 审计日志与工具调用日志。
- **RAG 知识库**：文档上传/解析/切分（递归字符 + 重叠）/异步向量化/文档管理；混合检索（向量 + 关键词 RRF 融合）+ Rerank + 答案引用来源 + Metadata Filter；向量持久化于 pgvector。
- **端到端可观测**：统一 Trace ID 贯穿 Router/Agent/检索/工具/审批，写入 `agent_traces`/`tool_call_logs`；OpenTelemetry span 可选 + Prometheus 指标 + Grafana 面板。
- **可运行**：Docker Compose 一键启动 API/PostgreSQL/Redis/pgvector/Worker/Prometheus/Grafana；SQLite + fakeredis 离线测试。
- **测试完备**：94+ 用例，覆盖数据层/认证/限流/幂等/工具安全/审批 FSM/RAG/Router/白名单/端到端。

## 简历描述（可直接使用）

- 基于 FastAPI + SQLAlchemy 2.0 + PostgreSQL + Redis 实现企业级多 Agent 智能客服系统，覆盖电商售前/售后场景。
- 设计 Router Agent → 专用 Agent → ToolRegistry 编排链，通过工具白名单与 RBAC 限制售前 Agent 发起退款等高风险操作。
- 实现 RAG 知识库（文档上传/切分/向量化/混合检索 + Rerank + 引用来源），向量持久化于 pgvector。
- 引入 JWT 认证、订单归属校验（防 IDOR）、退款/退货/改地址状态机、人工审批、Redis 限流与幂等、append-only 审计。
- 统一 Trace ID + AgentTrace/ToolCallLog + OpenTelemetry/Prometheus 实现端到端可观测。
- Docker Compose 一键启动 API/PG/Redis/Worker/Prometheus/Grafana；pytest 94+ 用例，ruff 全绿。

## 面试讲解稿（约 5 分钟）

1. **背景**：电商客服，售前咨询 + 售后订单/退款/退货，需要多 Agent + 安全 + 可观测。
2. **架构**：渠道 → MessageBus → RouterAgent（分类 + 置信度门限 + 转人工）→ 售前/售后 Agent → Runner（tool-calling + 白名单）→ Guardrail。
3. **安全亮点**：① JWT + RBAC 四角色；② 订单/退款工具强制归属校验防 IDOR；③ 改单二次确认、退货退款人工审批 FSM；④ Redis 分布式限流 + 幂等键；⑤ append-only 审计 + 工具调用日志。
4. **RAG**：文档上传 → 切分（递归字符 + 重叠）→ 向量化 → pgvector 持久化；检索 = 向量 + 关键词 RRF 融合 + Rerank + 引用来源 + Metadata Filter。
5. **可观测**：统一 Trace ID 贯穿 Router/Agent/工具/审批，写 AgentTrace/ToolCallLog；OTel span 可选；Prometheus 指标 + Grafana 面板。
6. **工程化**：Docker Compose 一键（API/PG/Redis/pgvector/Worker/Prometheus/Grafana）；SQLite + fakeredis 离线测试；94+ 用例覆盖核心路径。
7. **权衡**：向量库选 pgvector（与业务库统一、无新组件）而非 Qdrant；Router 用轻量分类器而非 LLM 工具路由（更快更省）；Rerank 用关键词重叠加权而非 reranker 模型（零依赖）。
