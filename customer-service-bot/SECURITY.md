# 安全策略

## 报告漏洞

发现安全漏洞请**不要**公开提 issue，而是私下联系维护者，附：
- 漏洞描述与影响
- 复现步骤
- 建议修复（可选）

我们将在 72 小时内确认收到，并在修复后公开致谢。

## 安全设计要点（本仓库已实现）

- 认证：JWT（access/refresh）+ RBAC（customer/agent/lead/admin）。
- 授权：订单/退款/退货工具强制校验调用者身份与订单归属（防 IDOR）。
- 高风险操作：改单二次确认、退货/退款人工审批 FSM。
- 横切：Redis 分布式限流、幂等键、append-only 审计日志。
- 密钥：`SecretStr` 脱敏；启动期校验生产必须设置 `JWT_SECRET`/`INIT_ADMIN_PASSWORD`。

## 你必须做的

- **不要提交真实 API Key、数据库密码、用户隐私数据**到仓库。
- 使用 `.env`（已被 `.gitignore` 排除）管理密钥；仓库仅提供 `.env.example` 占位。
- 生产部署前轮换所有默认密钥。
- 启用 HTTPS 反向代理；仅在可信代理后信任 `X-Forwarded-For`。
