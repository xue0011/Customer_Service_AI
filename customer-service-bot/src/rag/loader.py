"""从 data/ 示例数据加载为 Document（首次 seed 用）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from .types import Document


class DocumentLoader:
    """从 data/ 目录加载产品/FAQ/政策为 Document。"""

    def __init__(self, data_dir: str = "./data") -> None:
        self.data_dir = Path(data_dir)

    def load_all(self) -> list[Document]:
        docs: list[Document] = []
        docs.extend(self._load_products())
        docs.extend(self._load_faq())
        docs.extend(self._load_policies())
        return docs

    def _load_products(self) -> list[Document]:
        docs: list[Document] = []
        d = self.data_dir / "products"
        if not d.exists():
            return docs
        for f in d.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                docs.append(self._product_to_doc(data))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[RAG/loader] 产品加载失败 {f.name}: {e}")
        return docs

    @staticmethod
    def _product_to_doc(data: dict[str, Any]) -> Document:
        parts = [
            f"产品名称: {data.get('name', '')}",
            f"品牌: {data.get('brand', '')}",
            f"类别: {data.get('subcategory', '')} {data.get('category', '')}",
            f"描述: {data.get('description', '')}",
        ]
        specs = data.get("specs", {})
        if specs:
            parts.append(f"规格: {' '.join(f'{k}:{v}' for k, v in specs.items())}")
        variants = data.get("variants", [])
        colors = sorted({v.get("color", "") for v in variants})
        sizes = sorted({v.get("size", "") for v in variants if v.get("size")})
        prices = [v.get("price", 0) for v in variants]
        if colors:
            parts.append(f"可选颜色: {' '.join(colors)}")
        if sizes:
            parts.append(f"可选尺码: {' '.join(sizes)}")
        if prices:
            parts.append(f"价格区间: ¥{min(prices)}-¥{max(prices)}")
        return Document(
            id=data.get("base_product_id", ""),
            content=" | ".join(parts),
            metadata={
                "name": data.get("name"), "brand": data.get("brand"),
                "category": data.get("category"),
                "min_price": min(prices) if prices else None,
                "max_price": max(prices) if prices else None,
                "available_colors": colors, "available_sizes": sizes,
                "is_returnable": data.get("is_returnable", True),
            },
            source="data/products",
            category="product",
        )

    def _load_faq(self) -> list[Document]:
        docs: list[Document] = []
        p = self.data_dir / "faq" / "faq.json"
        if not p.exists():
            return docs
        try:
            for item in json.loads(p.read_text(encoding="utf-8")):
                docs.append(Document(
                    id=item.get("id", ""),
                    content=f"问题: {item.get('question', '')} | 答案: {item.get('answer', '')}",
                    metadata={"question": item.get("question"), "answer": item.get("answer"),
                              "category": item.get("category"), "tags": item.get("tags", [])},
                    source=str(p), category="faq",
                ))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[RAG/loader] FAQ 加载失败: {e}")
        return docs

    def _load_policies(self) -> list[Document]:
        docs: list[Document] = []
        d = self.data_dir / "policies"
        if not d.exists():
            return docs
        for f in d.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                for i, rule in enumerate(data.get("rules", [])):
                    docs.append(Document(
                        id=f"{f.stem}_{i}",
                        content=f"政策: {data.get('policy_name', '')} | {rule.get('condition', '')}: {rule.get('description', '')}",
                        metadata={"policy_name": data.get("policy_name"),
                                  "condition": rule.get("condition"),
                                  "description": rule.get("description"),
                                  "exceptions": rule.get("exceptions", [])},
                        source=str(f), category="policy",
                    ))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[RAG/loader] 政策加载失败 {f.name}: {e}")
        return docs
