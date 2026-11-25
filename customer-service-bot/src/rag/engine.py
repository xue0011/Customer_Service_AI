"""RAG 引擎门面：兼容旧 RAGEngine 接口，内部委托 DocumentManager/Retriever。

设计选择：向量存 DB（JSON list，应用层 cosine，兼容 SQLite 测试）；
生产可启用 pgvector Vector 列 + ANN 索引（见 MIGRATION）。替代方案 Qdrant（独立服务，
更高吞吐但多组件）——选 pgvector/DB 以与业务库统一、无新组件。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from ..database.db import get_session_factory
from ..tools.embedding_client import EmbeddingClient
from .indexer import DocumentManager
from .loader import DocumentLoader
from .repositories import RAGRepository
from .retriever import Retriever
from .types import SearchResult

try:
    from ..infra.context import get_trace_id  # 可选 Trace 关联
except Exception:  # noqa: BLE001
    get_trace_id = None  # type: ignore[assignment]


def _in_price(r: SearchResult, pr: tuple[float, float]) -> bool:
    mp = r.document.metadata.get("min_price")
    xp = r.document.metadata.get("max_price")
    if mp is None and xp is None:
        return True
    try:
        mn = float(mp) if mp is not None else 0
        mx = float(xp) if xp is not None else float("inf")
        return not (mx < pr[0] or mn > pr[1])
    except (TypeError, ValueError):
        return True


class RAGEngine:
    """RAG 引擎（门面）。"""

    def __init__(
        self, data_dir: str = "./data", embedding_model: str | None = None,
        product_repo=None, faq_repo=None, policy_repo=None,
    ) -> None:
        self.data_dir = data_dir
        self._embedding = EmbeddingClient(model=embedding_model)
        self._loader = DocumentLoader(data_dir)
        self._indexer = DocumentManager(self._embedding)
        self._retriever = Retriever(self._embedding)
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        try:
            factory = get_session_factory()
            async with factory() as s:
                docs = await RAGRepository(s).list_documents()
            if not docs:
                logger.info("[RAG] 知识库为空，从 data/ seed")
                await self._seed_from_data()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[RAG] 初始化失败（DB 不可用）: {e}")
        self._initialized = True

    async def _seed_from_data(self) -> None:
        for d in self._loader.load_all():
            try:
                doc_id = await self._indexer.upload(
                    source=d.source, content=d.content, category=d.category,
                    title=d.metadata.get("name") or d.id, metadata=d.metadata,
                )
                await self._indexer.process(doc_id)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[RAG] seed 文档 {d.id} 失败: {e}")

    async def search(
        self, query: str, search_type: str = "text", top_k: int = 5,
        category: str = "all", price_range: tuple[float, float] | None = None,
        tags: list[str] | None = None, metadata_filter: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        if not self._initialized:
            await self.initialize()
        if not query.strip():
            return []
        results = await self._retriever.search(
            query, category=category, top_k=top_k, metadata_filter=metadata_filter,
        )
        if price_range:
            results = [r for r in results if _in_price(r, price_range)]
        return results

    def get_document_count(self) -> int:
        """同步占位（旧接口兼容）；真实数量用 list_documents。"""
        return 0

    def get_categories(self) -> dict[str, int]:
        return {}


_rag_instance: RAGEngine | None = None


def get_rag_engine(
    data_dir: str = "./data", product_repo=None, faq_repo=None, policy_repo=None,
) -> RAGEngine:
    """全局 RAG 引擎单例。"""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = RAGEngine(data_dir, product_repo=product_repo, faq_repo=faq_repo, policy_repo=policy_repo)
    return _rag_instance
