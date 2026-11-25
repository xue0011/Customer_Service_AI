"""幂等测试（Redis SETNX + 内存降级）。"""

from __future__ import annotations

import pytest

from src.infra.idempotency import acquire, get_result, reset_memory_idempotency, set_result

pytestmark = pytest.mark.asyncio


async def test_acquire_first_then_duplicate():
    reset_memory_idempotency()
    assert await acquire("idem-1") is True
    assert await acquire("idem-1") is False       # 重复提交


async def test_set_and_get_result():
    reset_memory_idempotency()
    await acquire("idem-2")
    await set_result("idem-2", "done", {"ok": 1})
    r = await get_result("idem-2")
    assert r is not None
    assert r["status"] == "done"
    assert r["result"] == {"ok": 1}


async def test_empty_key_no_op():
    reset_memory_idempotency()
    assert await acquire("") is True
