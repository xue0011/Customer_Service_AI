"""幂等控制（Redis SETNX，内存降级）。

高风险工具（退货/退款/改单）应携带 Idempotency-Key，重复提交只执行一次。
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any

from .redis_client import get_redis

_mem_store: dict[str, dict[str, Any]] = defaultdict(dict)


async def acquire(key: str, ttl: int = 86400) -> bool:
    """尝试占用幂等键。True=获得（可执行），False=重复提交。"""
    if not key:
        return True  # 未带 key 不强制幂等
    r = await get_redis()
    if r is None:
        return _mem_acquire(key, ttl)
    return bool(await r.set(key, "pending", nx=True, ex=ttl))


async def set_result(key: str, status: str, result: Any, ttl: int = 86400) -> None:
    if not key:
        return
    r = await get_redis()
    if r is None:
        _mem_store[key] = {"status": status, "result": result}
        return
    payload = json.dumps({"status": status, "result": result}, ensure_ascii=False, default=str)
    await r.set(key, payload, ex=ttl)


async def get_result(key: str) -> dict[str, Any] | None:
    if not key:
        return None
    r = await get_redis()
    if r is None:
        return _mem_store.get(key)
    v = await r.get(key)
    if v is None:
        return None
    if v == "pending":
        return {"status": "pending", "result": None}
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return {"status": "done", "result": None}


def _mem_acquire(key: str, ttl: int) -> bool:
    if key in _mem_store:
        return False
    _mem_store[key] = {"status": "pending", "result": None, "_t": time.time()}
    return True


def reset_memory_idempotency() -> None:
    """测试用：清空内存幂等状态。"""
    _mem_store.clear()
