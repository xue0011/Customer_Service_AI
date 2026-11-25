"""检索器：向量 + 关键词 RRF 融合 + Rerank + 引用来源（验收2/3）。"""

from __future__ import annotations

import math
from typing import Any

from loguru import logger

from ..database.db import get_engine, get_session_factory
from ..tools.embedding_client import EmbeddingClient
from .repositories import RAGRepository
from .types import Citation, Document, SearchResult


def _cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a[:n], b[:n], strict=False))
    na = math.sqrt(sum(x * x for x in a[:n]))
    nb = math.sqrt(sum(y * y for y in b[:n]))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _highlights(text: str, query: str, window: int = 40) -> list[str]:
    if not text:
        return []
    ql = query.lower()
    tl = text.lower()
    idx = tl.find(ql)
    if idx < 0:
        for w in ql.split()[:3]:
            idx = tl.find(w)
            if idx >= 0:
                break
    if idx < 0:
        return [text[:100] + ("..." if len(text) > 100 else "")]
    start = max(0, idx - window)
    end = min(len(text), idx + len(ql) + window)
    snip = text[start:end]
    if start > 0:
        snip = "..." + snip
    if end < len(text):
        snip = snip + "..."
    return [snip]


def _matches_metadata(meta: dict, mf: dict[str, Any] | None) -> bool:
    if not mf:
        return True
    for k, v in mf.items():
        if meta.get(k) != v:
            return False
    return True


def _is_pg() -> bool:
    try:
        return get_engine().dialect.name == "postgresql"
    except Exception:  # noqa: BLE001
        return False


async def _search_pg(query: str, q_emb: list[float], category: str, top_k: int) -> list[SearchResult]:
    """生产 pgvector ANN 查询（PG，ORDER BY <=>）；失败返回空触发回退应用层。

    注：embedding_vec 维度需与迁移 0002 一致；metadata_filter 仅在应用层路径生效。
    """
    import json

    from sqlalchemy import text

    factory = get_session_factory()
    vec_str = "[" + ",".join(f"{x:.7f}" for x in q_emb) + "]"
    where = "WHERE d.status = 'ready'"
    params: dict[str, Any] = {"q": vec_str, "k": top_k}
    if category and category != "all":
        where += " AND d.category = :cat"
        params["cat"] = category
    sql = text(f"""
        SELECT e.id, e.document_id, e.chunk_text, e.metadata,
               1 - (e.embedding_vec <=> CAST(:q AS vector)) AS score
        FROM rag_embeddings e JOIN rag_documents d ON e.document_id = d.id
        {where}
        ORDER BY e.embedding_vec <=> CAST(:q AS vector)
        LIMIT :k
    """)
    try:
        async with factory() as s:
            r = await s.execute(sql, params)
            rows = r.all()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[RAG] pgvector 查询失败，回退应用层：{e}")
        return []
    results: list[SearchResult] = []
    for row in rows:
        meta = row[3]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:  # noqa: BLE001
                meta = {}
        meta = meta or {}
        doc = Document(id=row[1], content=row[2], metadata=meta, source=meta.get("source", ""), category=meta.get("category", category))
        cit = Citation(document_id=row[1], source=meta.get("source", ""), title=meta.get("title", ""), chunk_text=row[2], score=row[4], metadata=meta)
        results.append(SearchResult(document=doc, score=row[4], highlights=_highlights(row[2], query), citations=[cit]))
    return results


class Retriever:
    """混合检索（向量 + 关键词 RRF）+ Rerank + 引用。"""

    def __init__(self, embedding_client: EmbeddingClient | None = None) -> None:
        self._embedding = embedding_client or EmbeddingClient()

    async def search(
        self, query: str, category: str = "all", top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        q_emb = await self._embedding.embed_query(query) if self._embedding.available else None

        # 生产 pgvector ANN（PG + 向量可用）；失败回退应用层 cosine
        if q_emb is not None and _is_pg():
            pg = await _search_pg(query, q_emb, category, top_k)
            if pg:
                return pg

        factory = get_session_factory()
        async with factory() as s:
            candidates = await RAGRepository(s).get_embeddings(category)
        if not candidates:
            return []
        candidates = [(e, c) for e, c in candidates if _matches_metadata(e.metadata_ or {}, metadata_filter)]
        if not candidates:
            return []

        vec_scores: dict[int, tuple[float, Any, str]] = {}
        for emb, cat in candidates:
            score = _cosine(q_emb, emb.embedding) if (q_emb and emb.embedding) else 0.0
            vec_scores[emb.id] = (score, emb, cat)

        kw_scores: dict[int, float] = {}
        ql = query.lower()
        for emb, _cat in candidates:
            text = (emb.chunk_text or "").lower()
            if ql and ql in text:
                kw_scores[emb.id] = 0.5 + 0.1 * text.count(ql)
            else:
                overlap = sum(1 for w in ql.split() if w and w in text)
                kw_scores[emb.id] = 0.1 * overlap

        # RRF 融合
        k = 60
        vec_ranked = sorted(vec_scores.items(), key=lambda x: x[1][0], reverse=True)
        kw_ranked = sorted(kw_scores.items(), key=lambda x: x[1], reverse=True)
        rrf: dict[int, float] = {}
        for rank, (eid, _) in enumerate(vec_ranked, 1):
            rrf[eid] = rrf.get(eid, 0) + 1 / (k + rank)
        for rank, (eid, _) in enumerate(kw_ranked, 1):
            rrf[eid] = rrf.get(eid, 0) + 1 / (k + rank)

        # Rerank：RRF + 向量分 + 关键词重叠加权
        def final_score(eid: int) -> float:
            vscore = vec_scores[eid][0]
            kw = kw_scores.get(eid, 0.0)
            return rrf.get(eid, 0.0) + 0.2 * vscore + 0.1 * kw

        top = sorted(rrf.keys(), key=final_score, reverse=True)[:top_k]
        results: list[SearchResult] = []
        for eid in top:
            vscore, emb, cat = vec_scores[eid]
            meta = emb.metadata_ or {}
            doc = Document(
                id=emb.document_id, content=emb.chunk_text, metadata=meta,
                source=meta.get("source", ""), category=cat,
            )
            cit = Citation(
                document_id=emb.document_id, source=meta.get("source", ""),
                title=meta.get("title", ""), chunk_text=emb.chunk_text,
                score=vscore, metadata=meta,
            )
            results.append(SearchResult(
                document=doc, score=final_score(eid),
                highlights=_highlights(emb.chunk_text, query), citations=[cit],
            ))
        logger.debug(f"[RAG/retriever] 查询 '{query}' 命中 {len(results)} (候选 {len(candidates)})")
        return results
