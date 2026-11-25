"""RAG 引擎集成测试（P1：DB 向量库 + 混合检索，无 chromadb 依赖）。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.rag.engine import RAGEngine

pytestmark = pytest.mark.asyncio


@pytest.fixture
def data_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        products_dir = Path(tmpdir) / "products"
        products_dir.mkdir()
        product = {
            "base_product_id": "PROD-TEST-001",
            "name": "Test Red Dress",
            "brand": "Test Brand",
            "category": "clothing",
            "subcategory": "dress",
            "description": "A red dress made of cotton",
            "specs": {"material": "cotton", "style": "vintage"},
            "variants": [
                {"sku": "SKU-001-S", "color": "Red", "size": "S", "price": 399.00, "stock": 10},
                {"sku": "SKU-001-M", "color": "Red", "size": "M", "price": 399.00, "stock": 5},
            ],
            "available_sizes": ["S", "M"],
            "available_colors": ["Red"],
            "is_returnable": True,
        }
        (products_dir / "prod_test.json").write_text(json.dumps(product), encoding="utf-8")

        faq_dir = Path(tmpdir) / "faq"
        faq_dir.mkdir()
        faq = [
            {"id": "faq_001", "question": "How to return?", "answer": "Return within 7 days.", "category": "return", "tags": ["return"]},
        ]
        (faq_dir / "faq.json").write_text(json.dumps(faq), encoding="utf-8")

        policies_dir = Path(tmpdir) / "policies"
        policies_dir.mkdir()
        policy = {
            "policy_name": "Return Policy",
            "rules": [{"condition": "7-day return", "description": "Return within 7 days"}],
        }
        (policies_dir / "return_policy.json").write_text(json.dumps(policy), encoding="utf-8")

        yield tmpdir


class TestRAGEngine:
    async def test_initialize_and_search_products(self, data_dir):
        eng = RAGEngine(data_dir=data_dir)
        await eng.initialize()
        r = await eng.search("red dress", category="product", top_k=3)
        assert len(r) >= 1

    async def test_search_faq(self, data_dir):
        eng = RAGEngine(data_dir=data_dir)
        await eng.initialize()
        r = await eng.search("return", category="faq", top_k=3)
        assert len(r) >= 1
        assert r[0].document.category == "faq"

    async def test_search_policy(self, data_dir):
        eng = RAGEngine(data_dir=data_dir)
        await eng.initialize()
        r = await eng.search("return", category="policy", top_k=3)
        assert len(r) >= 1

    async def test_empty_query(self, data_dir):
        eng = RAGEngine(data_dir=data_dir)
        await eng.initialize()
        assert await eng.search("") == []
