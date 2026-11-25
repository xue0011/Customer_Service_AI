# GitHub 发布前检查清单

## 密钥与隐私
- [ ] `.env` 不在仓库（`.gitignore` 含）；仅提交 `.env.example`（占位值）。
- [ ] 无真实 API Key / 数据库密码 / 用户隐私（`grep -rE "sk-|password=|13[0-9]{9}"` 检查）。
- [ ] 默认 `JWT_SECRET` / `ADMIN_TOKEN` 标注 change-me，启动校验生产必填。

## 可运行
- [ ] `docker compose up --build` 一键启动，`GET /health` 返回 200。
- [ ] `pip install -e ".[dev]" && pytest tests/ -q` 全绿。
- [ ] `ruff check src/ tests/` 通过。
- [ ] `BASE=http://localhost:8000 ./scripts/api_demo.sh` 示例可跑。
- [ ] Grafana `http://localhost:3000`（admin/admin）可见面板。

## 代码与测试
- [ ] 核心模块有单元测试；`tests/test_e2e.py` 通过。
- [ ] 无假绿测试（无 `try/except: pass`、无恒真断言）。
- [ ] 工具写操作有归属校验 + 审计；高风险有确认 / 审批。
- [ ] 新增表有 Alembic 迁移（或 `init_db` 兼容）。

## 文档
- [ ] README：架构图 / 快速开始 / 配置 / API / 测试 / 部署拓扑 完整。
- [ ] `LICENSE` / `CONTRIBUTING.md` / `CODE_OF_CONDUCT.md` / `SECURITY.md` 存在。
- [ ] `MIGRATION.md` 说明破坏性变更。
- [ ] `docs/HIGHLIGHTS.md` 亮点 / 简历 / 面试稿。

## CI 与可观测
- [ ] GitHub Actions（test / lint / docker build）通过。
- [ ] Prometheus `/metrics` + Grafana 面板可访问。

## 安全
- [ ] 轮换 `.env` 中所有默认密钥（若曾误提交，按 `SECURITY.md` 处理）。
- [ ] 容器以非 root 运行；healthcheck 就绪。
- [ ] 反代启用 HTTPS；仅在可信代理后信任 `X-Forwarded-For`。
