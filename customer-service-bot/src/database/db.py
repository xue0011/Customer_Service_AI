"""
异步数据库引擎与会话工厂。

生产：PostgreSQL（asyncpg）；测试：SQLite（aiosqlite）。
通过 DATABASE_URL 或散字段配置，见 config.DatabaseConfig。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config.settings import get_config
from .models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine() -> AsyncEngine:
    cfg = get_config().database
    url = cfg.resolved_url()
    is_sqlite = url.startswith("sqlite")
    kwargs: dict[str, Any] = {"echo": cfg.echo}
    if not is_sqlite:
        # PG 使用连接池；SQLite 不接受池参数
        kwargs.update(
            pool_size=cfg.pool_size,
            max_overflow=cfg.max_overflow,
            pool_recycle=cfg.pool_recycle,
            pool_pre_ping=True,
        )
    else:
        # SQLite 需要 check_same_thread=False + StaticPool 以便跨连接共享 :memory:
        from sqlalchemy.pool import StaticPool

        kwargs.update(connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_async_engine(url, **kwargs)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：提供事务性异步会话。"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """创建所有表（测试与首次开发用；生产请用 Alembic 迁移）。"""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose() -> None:
    """释放引擎（测试清理 / 应用关闭）。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
