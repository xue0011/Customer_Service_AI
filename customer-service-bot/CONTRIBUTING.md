# 贡献指南

感谢你考虑为 customer-service-bot 贡献代码！本文档面向第一次接触本项目的开发者。

## 开发环境准备

```bash
git clone <repo-url> && cd customer-service-bot
python -m venv .venv && source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
pytest tests/ -q   # 应全部通过
```

本地测试无需真实 PostgreSQL/Redis：测试用 SQLite + fakeredis（见 `tests/conftest.py`）。

## 开发流程

1. Fork → 新建分支：`git checkout -b feat/your-feature`
2. 编码：保持模块边界清晰（路由层只编排，业务逻辑放专用模块）。
3. 本地校验：
   ```bash
   ruff check src/ tests/
   pytest tests/ -q
   ```
4. 提交：遵循 `feat: ...` / `fix: ...` / `docs: ...` 约定式提交。
5. PR：说明动机、改动点、测试情况；关联相关 issue。

## 代码规范

- Python 3.11+，类型注解齐全；通过 `ruff check`。
- 新增工具继承 `BaseTool`，自动获得参数校验/权限/超时/审计。
- 新增 Agent 继承 `BaseAgent`，声明工具白名单。
- 写操作必须经归属校验（IDOR）与审计。
- 不提交真实密钥/密码/隐私数据；示例用占位符。

## 模块边界

| 层 | 职责 | 不要做 |
|---|---|---|
| `api/` | HTTP 路由 + 依赖注入 | 业务逻辑 |
| `agents/` + `core/` | 编排（Router/Loop/Runner） | 直接写 SQL |
| `tools/` | 工具执行 + 安全层 | 跨工具编排 |
| `rag/` | 文档/检索 | 业务状态机 |
| `approval/` | 状态机 | HTTP 处理 |
| `database/` | ORM/仓储 | 业务规则 |

## 报告问题

提 issue 时附：复现步骤、期望/实际行为、日志（去除敏感信息）。

再次感谢你的贡献！
