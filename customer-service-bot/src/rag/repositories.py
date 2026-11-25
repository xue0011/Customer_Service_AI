"""RAG 文档与向量仓储。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import RAGDocument, RAGEmbedding


class RAGRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_documents(self, category: str | None = None) -> list[RAGDocument]:
        stmt = select(RAGDocument)
        if category and category != "all":
            stmt = stmt.where(RAGDocument.category == category)
        r = await self.session.execute(stmt.order_by(RAGDocument.created_at.desc()))
        return list(r.scalars().all())

    async def get_document(self, doc_id: str) -> RAGDocument | None:
        return await self.session.get(RAGDocument, doc_id)

    async def create_document(self, data: dict[str, Any]) -> RAGDocument:
        doc = RAGDocument(**{k: v for k, v in data.items() if hasattr(RAGDocument, k) or k == "metadata"})
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def update_status(
        self, doc_id: str, status: str, chunks_count: int | None = None
    ) -> None:
        doc = await self.session.get(RAGDocument, doc_id)
        if doc:
            doc.status = status
            if chunks_count is not None:
                doc.chunks_count = chunks_count
            await self.session.flush()

    async def delete_document(self, doc_id: str) -> None:
        await self.session.execute(delete(RAGEmbedding).where(RAGEmbedding.document_id == doc_id))
        await self.session.execute(delete(RAGDocument).where(RAGDocument.id == doc_id))
        await self.session.flush()

    async def replace_embeddings(
        self, document_id: str, chunks: list[dict[str, Any]]
    ) -> None:
        """替换文档的所有分块向量。chunks: [{chunk_index, chunk_text, embedding, metadata}]"""
        await self.session.execute(delete(RAGEmbedding).where(RAGEmbedding.document_id == document_id))
        for c in chunks:
            self.session.add(RAGEmbedding(
                document_id=document_id,
                chunk_index=c.get("chunk_index", 0),
                chunk_text=c.get("chunk_text", ""),
                embedding=c.get("embedding"),
                metadata_=c.get("metadata", {}),
            ))
        await self.session.flush()

    async def get_embeddings(self, category: str | None = None) -> list[RAGEmbedding]:
        """取候选分块（可按 category 过滤）。"""
        if category and category != "all":
            stmt = (
                select(RAGEmbedding, RAGDocument.category)
                .join(RAGDocument, RAGEmbedding.document_id == RAGDocument.id)
                .where(RAGDocument.category == category)
                .where(RAGDocument.status == "ready")
            )
        else:
            stmt = (
                select(RAGEmbedding, RAGDocument.category)
                .join(RAGDocument, RAGEmbedding.document_id == RAGDocument.id)
                .where(RAGDocument.status == "ready")
            )
        r = await self.session.execute(stmt)
        result = []
        for emb, cat in r.all():
            result.append((emb, cat))
        return result
