"""限流测试（fakeredis 分布式滑动窗口 + 内存降级）。"""

from __future__ import annotations

import pytest

from src.infra.ratelimit import check_rate_limit, reset_memory_limiter

pytestmark = pytest.mark.asyncio


async def test_rate_limit_allows_within_window():
    reset_memory_limiter()
    for _ in range(5):
        assert await check_rate_limit("user:alice", max_requests=5, window=60) is True


async def test_rate_limit_blocks_over_limit():
    reset_memory_limiter()
    for _ in range(3):
        await check_rate_limit("user:bob", max_requests=3, window=60)
    assert await check_rate_limit("user:bob", max_requests=3, window=60) is False


async def test_rate_limit_isolated_keys():
    reset_memory_limiter()
    for _ in range(2):
        await check_rate_limit("user:carol", max_requests=2, window=60)
    assert await check_rate_limit("user:carol", max_requests=2, window=60) is False
    assert await check_rate_limit("user:dave", max_requests=2, window=60) is True
