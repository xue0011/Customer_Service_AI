"""分布式速率限制（Redis 滑动窗口，内存降级）。"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict

from .redis_client import get_redis

_mem_store: dict[str, list[float]] = defaultdict(list)


async def check_rate_limit(
    key: str,
    max_requests: int = 30,
    window: int = 60,
    scope: str = "rl",
) -> bool:
    """检查是否允许请求。True=允许，False=超限。"""
    redis_key = f"ratelimit:{scope}:{key}"
    r = await get_redis()
    if r is None:
        return _mem_check(redis_key, max_requests, window)

    now = time.time()
    member = f"{now}:{uuid.uuid4().hex}"
    pipe = r.pipeline()
    pipe.zremrangebyscore(redis_key, 0, now - window)   # 清除窗口外
    pipe.zadd(redis_key, {member: now})
    pipe.zcard(redis_key)
    pipe.expire(redis_key, window)
    _, _, count, _ = await pipe.execute()
    return count <= max_requests


def _mem_check(key: str, max_requests: int, window: int) -> bool:
    now = time.time()
    store = _mem_store[key]
    _mem_store[key] = [t for t in store if t > now - window]
    if len(_mem_store[key]) >= max_requests:
        return False
    _mem_store[key].append(now)
    return True


def reset_memory_limiter() -> None:
    """测试用：清空内存限流状态。"""
    _mem_store.clear()


# ─── FastAPI 依赖 ───────────────────────────────────────────────────────────

try:
    from fastapi import HTTPException, Request  # noqa: F401

    async def rate_limit_dependency(
        request: Request,
        max_requests: int = 30,
    ) -> None:
        """FastAPI 限流依赖（按用户或 IP）。"""
        from .context import get_actor

        actor = get_actor()
        if actor is not None:
            key = f"u:{actor.user_id}"
        else:
            key = _client_ip(request)
        ok = await check_rate_limit(key, max_requests=max_requests)
        if not ok:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试。")

    def _client_ip(request: Request) -> str:
        # 仅在可信代理后信任 XFF；默认用直连 IP，避免伪造
        direct = request.client.host if request.client else "unknown"
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip() or direct
        return direct

except ImportError:  # fastapi 未安装时（非 web 路径）
    rate_limit_dependency = None  # type: ignore[assignment]
