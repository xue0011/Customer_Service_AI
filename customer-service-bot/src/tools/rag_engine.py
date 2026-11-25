"""RAG 引擎 shim —— 旧路径兼容，实际实现见 src.rag。

保留此文件以兼容 `from .rag_engine import get_rag_engine` 的旧引用。
"""

from __future__ import annotations

from ..rag.engine import RAGEngine, get_rag_engine
from ..rag.types import Document, SearchResult

__all__ = ["RAGEngine", "get_rag_engine", "Document", "SearchResult"]
