"""
安全模块
─────────
提供简单的速率限制和管理员认证功能。

  - RateLimiter：基于滑动窗口的内存速率限制器
  - require_admin_token：管理员端点的令牌认证

配置（环境变量）：
  ADMIN_TOKEN：管理后台访问令牌。生产环境必须设置；
              未设置时仅在 APP_ENV=development 下放行（开发用），否则拒绝。
  APP_ENV：运行环境（development / production，默认 production）。
  RATE_LIMIT_PER_MINUTE：每分钟最大请求数（默认 30）
"""

from __future__ import annotations

import os
import time
from collections import defaultdict

from fastapi import HTTPException, Request
from loguru import logger


class RateLimiter:
    """基于滑动窗口的内存速率限制器。"""

    def __init__(self, max_requests: int = 30, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> bool:
        """检查是否允许请求。返回 True 表示允许，False 表示超限。"""
        now = time.time()
        window_start = now - self.window_seconds

        # 清理过期记录
        self._requests[key] = [t for t in self._requests[key] if t > window_start]

        if len(self._requests[key]) >= self.max_requests:
            return False

        self._requests[key].append(now)
        return True


# 全局速率限制器实例
_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """获取全局速率限制器。"""
    global _rate_limiter
    if _rate_limiter is None:
        max_req = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
        _rate_limiter = RateLimiter(max_requests=max_req, window_seconds=60)
    return _rate_limiter


def get_client_key(request: Request) -> str:
    """获取客户端标识（IP 或 forwarded IP）。"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request) -> None:
    """检查速率限制，超限则抛出 429。"""
    limiter = get_rate_limiter()
    key = get_client_key(request)
    if not limiter.check(key):
        raise HTTPException(
            status_code=429,
            detail="请求过于频繁，请稍后再试。",
        )


def _is_dev_mode() -> bool:
    """是否处于开发模式（允许未设 ADMIN_TOKEN 时放行管理端点）。"""
    return os.getenv("APP_ENV", "production").lower() == "development"


def require_admin_token(request: Request) -> None:
    """管理端点认证：检查 Authorization 头或 admin_token 查询参数。

    安全策略（默认拒绝）：
      - ADMIN_TOKEN 已设置 → 必须匹配，否则 401。
      - ADMIN_TOKEN 未设置 + APP_ENV=development → 放行并记警告（仅本地开发）。
      - ADMIN_TOKEN 未设置 + 非开发环境 → 503 拒绝，避免管理端点裸奔。
    """
    admin_token = os.getenv("ADMIN_TOKEN", "")

    if not admin_token:
        if _is_dev_mode():
            logger.warning("[security] ADMIN_TOKEN 未设置，开发模式下放行管理端点。")
            return
        raise HTTPException(
            status_code=503,
            detail="服务未配置管理令牌（ADMIN_TOKEN），管理端点暂不可用。",
        )

    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.query_params.get("admin_token", "")

    if not token or token != admin_token:
        raise HTTPException(
            status_code=401,
            detail="未授权：请提供有效的管理员令牌。",
        )
