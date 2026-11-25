"""RAG 类型：文档、引用、检索结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Document:
    """RAG 文档。"""

    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    category: str = ""  # product / faq / policy / manual


@dataclass
class Citation:
    """答案引用来源（可追溯）。"""

    document_id: str
    source: str
    title: str
    chunk_text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """检索结果。"""

    document: Document
    score: float
    highlights: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.document.id,
            "content": self.document.content,
            "metadata": self.document.metadata,
            "source": self.document.source,
            "category": self.document.category,
            "score": round(self.score, 4),
            "highlights": self.highlights,
            "citations": [
                {
                    "document_id": c.document_id,
                    "source": c.source,
                    "title": c.title,
                    "score": round(c.score, 4),
                    "snippet": c.chunk_text[:200],
                }
                for c in self.citations
            ],
        }
