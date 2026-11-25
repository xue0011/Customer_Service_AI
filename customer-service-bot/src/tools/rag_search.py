"""
RAG 检索工具
────────────
支持文本 + 图片的混合检索，用于增强售前 Agent 的产品推荐能力。

使用 RAGEngine 提供真实的 TF-IDF 关键词检索。
"""

from __future__ import annotations

from typing import Any

from .base import BaseTool
from .rag_engine import get_rag_engine


class RAGSearchTool(BaseTool):
    """RAG 检索工具 —— 支持文本和图片的多模态检索。"""

    def __init__(self, data_dir: str = "./data") -> None:
        super().__init__()
        self._data_dir = data_dir

    @property
    def name(self) -> str:
        return "rag_search"

    @property
    def description(self) -> str:
        return (
            '多模态 RAG 检索工具，用于根据描述搜索产品。'
            '当顾客描述需求（如红色连衣裙、适合夏天穿的）时使用。'
            '支持文本搜索、图片搜索（通过图片文字描述）、文本+图片联合搜索。'
            '返回匹配的产品列表，包含名称、价格、匹配度、描述和核心卖点。'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索描述文本，将顾客需求转化为产品关键词，如'红色连衣裙 春秋'",
                },
                "search_type": {
                    "type": "string",
                    "enum": ["text", "image", "hybrid"],
                    "description": "搜索类型：text=纯文本搜索, image=图片搜索（用文字描述图片内容）, hybrid=组合搜索",
                    "default": "text",
                },
                "category": {
                    "type": "string",
                    "enum": ["product", "faq", "policy", "all"],
                    "description": "搜索类别：product=产品, faq=常见问题, policy=政策, all=全部",
                    "default": "product",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量，建议3-5个",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """执行 RAG 检索。"""
        query = kwargs.get("query", "")
        search_type = kwargs.get("search_type", "text")
        category = kwargs.get("category", "product")
        top_k = kwargs.get("top_k", 5)

        engine = get_rag_engine(self._data_dir)
        results = await engine.search(
            query=query,
            search_type=search_type,
            top_k=top_k,
            category=category,
        )

        return {
            "query": query,
            "search_type": search_type,
            "category": category,
            "total_found": len(results),
            "results": [r.to_dict() for r in results],
        }
