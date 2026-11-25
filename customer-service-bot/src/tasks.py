"""异步任务队列（ARQ）—— Worker 承载 RAG 向量化等长任务（验收1）。

启动 worker：`arq src.tasks.WorkerSettings`（compose 已配置）。
设计选择：ARQ（原生 async、复用 Redis、轻量）。替代方案 Celery（成熟但较重、同步为主）。
"""

from __future__ import annotations

from loguru import logger

from .config.settings import get_config

try:
    from arq.connections import RedisSettings

    _HAS_ARQ = True
except ImportError:
    _HAS_ARQ = False
    RedisSettings = None  # type: ignore[assignment]


async def rag_index_document(ctx: dict, document_id: str) -> None:
    """对文档执行切分 + 向量化（供 worker 异步处理）。"""
    from .rag.indexer import DocumentManager

    await DocumentManager().process(document_id)
    logger.info(f"[worker] 文档 {document_id} 索引完成")


async def startup(ctx: dict) -> None:
    logger.info("[worker] ARQ worker 启动")


class WorkerSettings:
    """ARQ Worker 配置。"""

    functions = [rag_index_document]
    on_startup = startup

    @staticmethod
    def redis_settings() -> RedisSettings:
        cfg = get_config().redis
        if not _HAS_ARQ:
            raise RuntimeError("arq 未安装")
        return RedisSettings(
            host=cfg.host,
            port=cfg.port,
            password=cfg.password.get_secret_value() or None,
            db=cfg.db,
        )
