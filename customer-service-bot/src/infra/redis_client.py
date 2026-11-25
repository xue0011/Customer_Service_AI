"""Redis 客户端（会话缓存、限流、幂等）。

生产：连真实 Redis；测试：用 set_test_redis 注入 fakeredis。
未配置或不可用时返回 None，调用方降级到内存。
"""

from __future__ import annotations

import redis.asyncio as aioredis
from loguru import logger

from ..config.settings import get_config

_redis: aioredis.Redis | None = None
_test_redis: aioredis.Redis | None = None


def set_test_redis(r: aioredis.Redis | None) -> None:
    """测试用：注入 fakeredis（或其他 mock）。"""
    global _test_redis
    _test_redis = r


async def get_redis() -> aioredis.Redis | None:
    if _test_redis is not None:
        return _test_redis
    global _redis
    if _redis is not None:
        return _redis
    cfg = get_config().redis
    try:
        client = aioredis.from_url(cfg.url(), decode_responses=True)
        await client.ping()
        _redis = client
        return client
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[redis] 不可用，下游将降级内存：{e}")
        return None


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
