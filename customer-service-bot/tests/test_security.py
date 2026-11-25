"""安全模块测试。"""

import time

import pytest
from fastapi import HTTPException

from src.security import RateLimiter, get_rate_limiter, require_admin_token


class TestRateLimiter:
    """RateLimiter 单元测试。"""

    def test_allows_under_limit(self):
        """测试未超限允许请求。"""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            assert limiter.check("client_1") is True

    def test_blocks_over_limit(self):
        """测试超限拒绝请求。"""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            assert limiter.check("client_2") is True
        assert limiter.check("client_2") is False

    def test_different_clients_independent(self):
        """测试不同客户端计数独立。"""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        assert limiter.check("client_a") is True
        assert limiter.check("client_a") is True
        assert limiter.check("client_a") is False
        # 客户端 b 不受影响
        assert limiter.check("client_b") is True

    def test_window_expiry(self):
        """测试窗口过期后可重新请求。"""
        limiter = RateLimiter(max_requests=1, window_seconds=1)
        assert limiter.check("client_c") is True
        assert limiter.check("client_c") is False
        time.sleep(1.1)
        assert limiter.check("client_c") is True

    def test_get_rate_limiter_singleton(self):
        """测试全局单例。"""
        r1 = get_rate_limiter()
        r2 = get_rate_limiter()
        assert r1 is r2


class _FakeRequest:
    """轻量 Request 替身，避免拉起完整 ASGI 栈。"""

    def __init__(self, headers=None, query=None):
        self.headers = headers or {}
        self.query_params = query or {}


class TestRequireAdminToken:
    """require_admin_token 鉴权测试。"""

    def test_missing_token_rejected_in_production(self, monkeypatch):
        """生产环境未设 ADMIN_TOKEN → 503 拒绝。"""
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(HTTPException) as exc:
            require_admin_token(_FakeRequest())
        assert exc.value.status_code == 503

    def test_missing_token_allowed_in_dev(self, monkeypatch):
        """开发环境未设 ADMIN_TOKEN → 放行。"""
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        monkeypatch.setenv("APP_ENV", "development")
        # 不抛异常即视为通过
        require_admin_token(_FakeRequest())

    def test_missing_token_default_is_production(self, monkeypatch):
        """APP_ENV 未设置时默认按生产处理 → 503。"""
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        with pytest.raises(HTTPException) as exc:
            require_admin_token(_FakeRequest())
        assert exc.value.status_code == 503

    def test_valid_bearer_token_passes(self, monkeypatch):
        """正确 Bearer 令牌 → 放行。"""
        monkeypatch.setenv("ADMIN_TOKEN", "secret123")
        monkeypatch.setenv("APP_ENV", "production")
        req = _FakeRequest(headers={"Authorization": "Bearer secret123"})
        require_admin_token(req)

    def test_invalid_token_rejected(self, monkeypatch):
        """错误令牌 → 401。"""
        monkeypatch.setenv("ADMIN_TOKEN", "secret123")
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(HTTPException) as exc:
            require_admin_token(_FakeRequest(headers={"Authorization": "Bearer wrong"}))
        assert exc.value.status_code == 401

    def test_token_via_query_param(self, monkeypatch):
        """查询参数 admin_token 也生效。"""
        monkeypatch.setenv("ADMIN_TOKEN", "secret123")
        monkeypatch.setenv("APP_ENV", "production")

        class Q:
            def get(self, key, default=None):
                return "secret123" if key == "admin_token" else default

        require_admin_token(_FakeRequest(query=Q()))
