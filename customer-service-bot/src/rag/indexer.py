"""文档管理：上传/解析/切分/向量化/状态管理（验收1）。"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger

from ..database.db import get_session_factory
from ..tools.embedding_client import EmbeddingClient
from .chunker import chunk_text
from .repositories import RAGRepository


class DocumentManager:
    """知识库文档管理 + 异步向量化。"""

    def __init__(self, embedding_client: EmbeddingClient | None = None) -> None:
        self._embedding = embedding_client or EmbeddingClient()

    async def upload(
        self, source: str, content: str, category: str = "manual",
        title: str = "", metadata: dict[str, Any] | None = None,
    ) -> str:
        """上传文档（status=uploaded），返回 doc_id。"""
        doc_id = uuid.uuid4().hex
        factory = get_session_factory()
        async with factory() as s:
            await RAGRepository(s).create_document({
                "id": doc_id, "source": source, "category": category,
                "title": title, "content": content, "status": "uploaded",
                "metadata": metadata or {},
            })
            await s.commit()
        logger.info(f"[RAG/indexer] 上传文档 {doc_id} ({category}, {len(content)} 字符)")
        return doc_id

    async def process(self, document_id: str) -> None:
        """切分 + 向量化 + 入库（状态机：uploaded→chunking→embedding→ready/failed）。"""
        factory = get_session_factory()
        async with factory() as s:
            repo = RAGRepository(s)
            doc = await repo.get_document(document_id)
            if not doc:
                return
            await repo.update_status(document_id, "chunking")
            await s.commit()

        chunks = chunk_text(doc.content)
        embeddings = None
        if chunks and self._embedding.available:
            try:
                await self._set_status(document_id, "embedding")
                embeddings = await self._embedding.embed(chunks)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[RAG/indexer] 向量化失败 {document_id}: {e}")
                embeddings = None

        chunk_objs = [
            {
                "chunk_index": i,
                "chunk_text": c,
                "embedding": embeddings[i] if embeddings else None,
                "metadata": {"category": doc.category, "title": doc.title,
                             "source": doc.source, **(doc.metadata_ or {})},
            }
            for i, c in enumerate(chunks)
        ]
        async with factory() as s:
            repo = RAGRepository(s)
            await repo.replace_embeddings(document_id, chunk_objs)
            # PG：额外写 embedding_vec 供 ANN 检索（SQLite 跳过）
            try:
                if s.bind.dialect.name == "postgresql":
                    from sqlalchemy import text

                    for c in chunk_objs:
                        if c.get("embedding"):
                            vec = "[" + ",".join(f"{x:.7f}" for x in c["embedding"]) + "]"
                            await s.execute(text(
                                "UPDATE rag_embeddings SET embedding_vec = CAST(:v AS vector) "
                                "WHERE document_id = :doc AND chunk_index = :ci"
                            ), {"v": vec, "doc": document_id, "ci": c["chunk_index"]})
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[RAG/indexer] embedding_vec 写入跳过：{e}")
            await repo.update_status(document_id, "ready", chunks_count=len(chunks))
            await s.commit()
        logger.info(f"[RAG/indexer] 文档 {document_id} 处理完成（{len(chunks)} 块）")

    async def _set_status(self, document_id: str, status: str) -> None:
        factory = get_session_factory()
        async with factory() as s:
            await RAGRepository(s).update_status(document_id, status)
            await s.commit()

    async def list_documents(self, category: str | None = None) -> list[dict[str, Any]]:
        factory = get_session_factory()
        async with factory() as s:
            docs = await RAGRepository(s).list_documents(category)
        return [{"id": d.id, "source": d.source, "category": d.category, "title": d.title,
                 "status": d.status, "chunks_count": d.chunks_count, "created_at": d.created_at.isoformat() if d.created_at else None} for d in docs]

    async def get(self, document_id: str) -> dict[str, Any] | None:
        factory = get_session_factory()
        async with factory() as s:
            d = await RAGRepository(s).get_document(document_id)
        if not d:
            return None
        return {"id": d.id, "source": d.source, "category": d.category, "title": d.title,
                "content": d.content, "status": d.status, "chunks_count": d.chunks_count, "metadata": d.metadata_}

    async def delete(self, document_id: str) -> None:
        factory = get_session_factory()
        async with factory() as s:
            await RAGRepository(s).delete_document(document_id)
            await s.commit()
