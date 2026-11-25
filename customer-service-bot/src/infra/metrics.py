"""Prometheus 指标（验收8）。

使用 prometheus-fastapi-instrumentator 自动采集 HTTP 指标并暴露 /metrics。
未安装时降级（不暴露），保持可运行。
"""

from __future__ import annotations

from loguru import logger

try:
    from prometheus_fastapi_instrumentator import Instrumentator

    _HAS = True
except ImportError:
    _HAS = False
    Instrumentator = None  # type: ignore[assignment]


def setup_metrics(app) -> None:
    """在 FastAPI app 上挂载 Prometheus 指标。"""
    if not _HAS:
        logger.warning("[metrics] prometheus-fastapi-instrumentator 未安装，跳过 /metrics")
        return
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    logger.info("[metrics] Prometheus 指标已挂载于 /metrics")
