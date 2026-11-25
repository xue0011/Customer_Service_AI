"""
嵌入客户端（Embedding Client）
─────────────────────────────
封装 OpenAI 兼容的嵌入 API，异步生成文本向量。

使用与 LLM 相同的 API 配置（OPENAI_API_KEY、OPENAI_API_BASE）。
模型通过 EMBEDDING_MODEL 环境变量配置。
"""

from __future__ import annotations

import os

from loguru import logger


class EmbeddingClient:
    """OpenAI 兼容的异步嵌入 API 客户端。"""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
    ) -> None:
        # 默认使用与 LLM 相同的 API 配置（阿里云 DashScope）
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.api_base = api_base or os.getenv(
            "OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self.model = model or os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
        self.api_base = self.api_base.rstrip("/")

        self._client = None
        self._available = False
        self._dim: int | None = None
        self._init_client()

    def _init_client(self) -> None:
        """初始化异步 OpenAI 客户端。"""
        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base,
            )
            self._available = True
            logger.info(f"[Embedding] 异步客户端已初始化，模型: {self.model}, base: {self.api_base}")
        except ImportError:
            logger.warning("[Embedding] openai 未安装，嵌入功能不可用")
        except Exception as e:
            logger.error(f"[Embedding] 初始化失败: {e}")

    @property
    def available(self) -> bool:
        return self._available and bool(self.api_key)

    @property
    def dimension(self) -> int | None:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        """异步批量生成嵌入向量。失败返回 None（调用方回退到关键词匹配）。"""
        if not self.available or not self._client:
            logger.warning("[Embedding] 客户端不可用，将回退到关键词匹配")
            return None

        try:
            truncated = [t[:8000] for t in texts]
            response = await self._client.embeddings.create(
                model=self.model,
                input=truncated,
            )
            embeddings = [d.embedding for d in response.data]
            if embeddings and self._dim is None:
                self._dim = len(embeddings[0])
                logger.info(f"[Embedding] 检测到嵌入维度: {self._dim}")
            return embeddings
        except Exception as e:
            logger.error(f"[Embedding] 嵌入失败: {e}")
            return None

    async def embed_query(self, text: str) -> list[float] | None:
        """异步为单个查询文本生成嵌入向量。失败返回 None。"""
        results = await self.embed([text])
        if results is None:
            return None
        return results[0] if results else None
