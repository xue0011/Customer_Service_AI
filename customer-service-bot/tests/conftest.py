"""pytest 全局配置：路径 + 测试环境（SQLite + fakeredis + admin Actor）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 将 src 目录添加到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 必须在任何 src 模块被 import 前设置环境变量
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("INIT_ADMIN_USERNAME", "admin")
os.environ.setdefault("INIT_ADMIN_PASSWORD", "testpass123")
os.environ.setdefault("AUDIT_ENABLED", "true")

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
async def _test_env():
    """每个测试前：重置单例 → 建表 → 注入 fakeredis → 注入 admin Actor。"""
    from src.config.settings import reset_config
    from src.database.db import dispose, init_db
    from src.infra.context import Actor, set_actor
    from src.infra.idempotency import reset_memory_idempotency
    from src.infra.ratelimit import reset_memory_limiter
    from src.infra.redis_client import set_test_redis

    reset_config()
    await dispose()
    set_test_redis(fakeredis.aioredis.FakeRedis(decode_responses=True))
    reset_memory_limiter()
    reset_memory_idempotency()
    await init_db()
    set_actor(Actor(user_id="test-admin", role="admin", display_name="测试管理员"))
    yield
    set_actor(None)
    await dispose()
    reset_config()
