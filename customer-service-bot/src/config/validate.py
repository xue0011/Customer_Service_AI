"""启动期环境变量校验（验收2）。

生产环境强制关键变量；开发环境宽松（便于本地运行）。
"""

from __future__ import annotations

from loguru import logger

from .settings import get_config


def validate_config() -> list[str]:
    """返回配置问题列表（空列表表示通过）。"""
    cfg = get_config()
    problems: list[str] = []

    if cfg.app_env == "production":
        if not cfg.jwt.secret.get_secret_value():
            problems.append("JWT_SECRET 未设置（生产必填，生成：python -c \"import secrets;print(secrets.token_urlsafe(48))\"）")
        if not cfg.rbac.superuser_password.get_secret_value():
            problems.append("INIT_ADMIN_PASSWORD 未设置（生产必填）")
        url = cfg.database.resolved_url()
        if not (url.startswith("postgresql") or url.startswith("sqlite")):
            problems.append("DATABASE_URL 未指向 PostgreSQL 或 SQLite")
        if cfg.jwt.secret.get_secret_value() in {
            "change-me-to-a-strong-random-secret",
            "test-secret-0123456789abcdef0123456789abcdef",
        }:
            problems.append("JWT_SECRET 为默认值，生产必须替换")
    else:
        if not cfg.jwt.secret.get_secret_value():
            logger.warning("[config] 开发环境未设 JWT_SECRET，使用弱默认（仅本地）")
    return problems


def assert_valid_config() -> None:
    problems = validate_config()
    if problems:
        raise RuntimeError("启动配置校验失败：\n - " + "\n - ".join(problems))
    logger.info("[config] 启动配置校验通过")
