"""
知识库查询工具
─────────────
用于查询店铺知识库，包括产品信息、FAQ、退换货政策等。

使用 RAGEngine 提供真实的 TF-IDF 关键词检索。
"""

from __future__ import annotations

from typing import Any

from .base import BaseTool
from .rag_engine import get_rag_engine


class KnowledgeBaseTool(BaseTool):
    """知识库查询工具 —— 检索店铺知识库中的信息。"""

    def __init__(
        self,
        data_dir: str = "./data",
        product_repo=None,
        faq_repo=None,
        policy_repo=None,
    ) -> None:
        super().__init__()
        self._data_dir = data_dir
        self._product_repo = product_repo
        self._faq_repo = faq_repo
        self._policy_repo = policy_repo

    @property
    def name(self) -> str:
        return "knowledge_base"

    @property
    def description(self) -> str:
        return (
            "查询店铺知识库，获取产品信息、FAQ（常见问题）、政策规则等。"
            "可以按类别筛选（产品/FAQ/政策），支持关键词搜索。"
            "当顾客询问产品规格、退换货政策、发货时间等需要查阅知识库的问题时使用。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，如产品名称、问题类型、政策关键词",
                },
                "category": {
                    "type": "string",
                    "enum": ["product", "faq", "policy", "all"],
                    "description": "知识库类别：product=产品信息, faq=常见问题, policy=政策规则, all=全部",
                    "default": "all",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量，默认3个",
                    "default": 3,
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """执行知识库查询。"""
        query = kwargs.get("query", "")
        category = kwargs.get("category", "all")
        top_k = kwargs.get("top_k", 3)

        engine = get_rag_engine(
            self._data_dir,
            product_repo=self._product_repo,
            faq_repo=self._faq_repo,
            policy_repo=self._policy_repo,
        )
        results = await engine.search(
            query=query,
            top_k=top_k,
            category=category,
        )

        return {
            "query": query,
            "category": category,
            "total_found": len(results),
            "results": [r.to_dict() for r in results],
        }
