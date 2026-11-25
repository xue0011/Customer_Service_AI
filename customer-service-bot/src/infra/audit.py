"""审计日志 sink：DB（append-only）+ 结构化文件双写。

工具调用日志（ToolCallLog）单独记录，便于查询工具执行情况。
所有写入使用独立会话，不污染业务事务。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from ..config.settings import get_config
from ..database.db import get_session_factory
from ..database.repositories_async import AuditRepository, ToolCallLogRepository
from .context import get_actor, get_correlation_id


def _record(action, resource, before, after, actor, correlation_id) -> dict[str, Any]:
    a = actor or get_actor()
    cid = correlation_id or get_correlation_id()
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "actor_id": a.user_id if a else None,
        "actor_role": a.role if a else None,
        "action": action,
        "resource": resource,
        "before": before,
        "after": after,
        "correlation_id": cid,
    }


def _file_append(record: dict[str, Any]) -> None:
    cfg = get_config().audit
    if not cfg.enabled:
        return
    path = Path(cfg.log_file)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[audit] 文件写入失败：{e}")


async def audit(
    action: str,
    resource: str = "",
    before: dict | None = None,
    after: dict | None = None,
    actor=None,
    correlation_id: str | None = None,
) -> None:
    """记录审计日志（DB + 文件）。"""
    record = _record(action, resource, before, after, actor, correlation_id)
    _file_append(record)
    cfg = get_config().audit
    if not cfg.enabled:
        return
    try:
        factory = get_session_factory()
        async with factory() as s:
            repo = AuditRepository(s)
            await repo.append(
                actor_id=record["actor_id"],
                actor_role=record["actor_role"],
                action=action,
                resource=resource,
                before=before,
                after=after,
                correlation_id=record["correlation_id"],
            )
            await s.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[audit] DB 写入失败：{e}")


async def log_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    result: dict | None,
    success: bool,
    error: str | None,
    duration_ms: float,
    session_id: str | None = None,
    trace_id: str | None = None,
    actor=None,
) -> None:
    """记录工具调用日志。"""
    a = actor or get_actor()
    cfg = get_config().audit
    if not cfg.enabled:
        return
    try:
        factory = get_session_factory()
        async with factory() as s:
            repo = ToolCallLogRepository(s)
            await repo.append({
                "session_id": session_id,
                "trace_id": trace_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "result": result,
                "success": success,
                "error": error,
                "duration_ms": duration_ms,
                "actor_id": a.user_id if a else None,
                "actor_role": a.role if a else None,
            })
            await s.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[audit] 工具日志写入失败：{e}")
