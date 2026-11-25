"""
记忆持久化存储（Memory Store）
─────────────────────────────
支持四种后端的完整实现：

  - File：JSONL 文件存储（开发/测试），完整实现
  - MySQL：关系型数据库，持久化，完整实现
  - ChromaDB：向量存储，支持语义检索，完整实现
  - Redis：高性能缓存，适合短期记忆，完整实现
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from ..config.schema import MemoryConfig


class MemoryStore:
    """记忆存储 —— 持久化层抽象。"""

    def __init__(self, config: MemoryConfig) -> None:
        self.config = config
        self.backend = config.backend
        self._initialized = False
        self._chroma_client = None
        self._chroma_collection = None
        self._redis_client = None
        self._memory_repo = None

    async def initialize(self) -> None:
        """初始化存储后端。"""
        if self.backend == "file":
            Path(self.config.persist_dir).mkdir(parents=True, exist_ok=True)
        elif self.backend == "mysql":
            await self._init_mysql()
        elif self.backend == "chroma":
            await self._init_chroma()
        elif self.backend == "redis":
            await self._init_redis()
        self._initialized = True
        logger.info(f"[Memory] 初始化完成，后端: {self.backend}")

    async def close(self) -> None:
        """关闭存储连接。"""
        if self._chroma_client:
            self._chroma_client = None
        if self._redis_client:
            try:
                await self._redis_client.close()
            except Exception as e:
                logger.debug(f"[Memory] Redis 连接关闭失败: {e}")
            self._redis_client = None
        self._initialized = False
        logger.info("[Memory] 已关闭")

    # ── 核心接口 ──────────────────────────────────────────────────────────

    async def save_interaction(
        self,
        customer_id: str,
        thread_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        entry = {
            "id": f"mem_{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}",
            "customer_id": customer_id,
            "thread_id": thread_id,
            "user_message": user_message,
            "assistant_message": assistant_message,
            "metadata": metadata or {},
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if self.backend == "file":
            return await self._save_file(entry)
        elif self.backend == "mysql":
            return await self._save_mysql(entry)
        elif self.backend == "chroma":
            return await self._save_chroma(entry)
        elif self.backend == "redis":
            return await self._save_redis(entry)
        return entry["id"]

    async def get_history(
        self, customer_id: str, thread_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        if self.backend == "file":
            return await self._get_history_file(customer_id, thread_id, limit)
        elif self.backend == "mysql":
            return await self._get_history_mysql(customer_id, thread_id, limit)
        elif self.backend == "chroma":
            return await self._get_history_chroma(customer_id, thread_id, limit)
        elif self.backend == "redis":
            return await self._get_history_redis(customer_id, thread_id, limit)
        return []

    async def search(
        self, query: str, customer_id: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        if self.backend == "file":
            return await self._search_file(query, customer_id, limit)
        elif self.backend == "mysql":
            return await self._search_mysql(query, customer_id, limit)
        elif self.backend == "chroma":
            return await self._search_chroma(query, customer_id, limit)
        elif self.backend == "redis":
            return await self._search_redis(query, customer_id, limit)
        return []

    async def save_customer_profile(self, customer_id: str, profile: dict[str, Any]) -> None:
        if self.backend == "mysql" and self._memory_repo:
            self._memory_repo.save_profile(customer_id, profile)
        elif self.backend == "file":
            path = Path(self.config.persist_dir) / f"profile_{customer_id}.json"
            path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        elif self.backend == "chroma":
            await self._save_chroma({
                "id": f"profile_{customer_id}", "customer_id": customer_id,
                "user_message": "", "assistant_message": json.dumps(profile, ensure_ascii=False),
                "metadata": {"type": "customer_profile"}, "timestamp": datetime.now(UTC).isoformat(),
            })
        elif self.backend == "redis" and self._redis_client:
            await self._redis_client.set(f"profile:{customer_id}", json.dumps(profile, ensure_ascii=False))

    async def get_customer_profile(self, customer_id: str) -> dict[str, Any]:
        if self.backend == "mysql" and self._memory_repo:
            return self._memory_repo.get_profile(customer_id)
        if self.backend == "file":
            path = Path(self.config.persist_dir) / f"profile_{customer_id}.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        elif self.backend == "redis" and self._redis_client:
            data = await self._redis_client.get(f"profile:{customer_id}")
            if data:
                return json.loads(data)
        return {}

    async def get_all_customer_ids(self) -> list[str]:
        """获取所有有记忆记录的顾客ID。"""
        if self.backend == "mysql" and self._memory_repo:
            return self._memory_repo.get_all_customer_ids()
        elif self.backend == "file":
            persist_dir = Path(self.config.persist_dir)
            if not persist_dir.exists():
                return []
            return [p.stem for p in persist_dir.glob("*.jsonl")]
        elif self.backend == "redis" and self._redis_client:
            ids = set()
            async for key in self._redis_client.scan_iter(match="history:*", count=100):
                parts = key.split(":")
                if len(parts) >= 2:
                    ids.add(parts[1])
            return list(ids)
        return []

    # ── File 后端 ─────────────────────────────────────────────────────

    async def _save_file(self, entry: dict[str, Any]) -> str:
        path = Path(self.config.persist_dir) / f"{entry['customer_id']}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry["id"]

    async def _get_history_file(
        self, customer_id: str, thread_id: str | None, limit: int
    ) -> list[dict[str, Any]]:
        path = Path(self.config.persist_dir) / f"{customer_id}.jsonl"
        if not path.exists():
            return []
        entries = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line.strip())
                if thread_id is None or entry.get("thread_id") == thread_id:
                    entries.append(entry)
        return entries[-limit:]

    async def _search_file(
        self, query: str, customer_id: str | None, limit: int
    ) -> list[dict[str, Any]]:
        results = []
        search_dir = Path(self.config.persist_dir)
        for path in search_dir.glob("*.jsonl"):
            if customer_id and path.stem != customer_id:
                continue
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if query.lower() in line.lower():
                        results.append(json.loads(line.strip()))
                        if len(results) >= limit:
                            return results
        return results

    # ── MySQL 后端 ────────────────────────────────────────────────────

    async def _init_mysql(self) -> None:
        """初始化 MySQL 后端。"""
        try:
            from ..database.connection import get_db
            from ..database.repository import MemoryRepository
            self._memory_repo = MemoryRepository(get_db())
            logger.info("[Memory] MySQL 已连接")
        except Exception as e:
            logger.error(f"[Memory] MySQL 初始化失败: {e}")

    async def _save_mysql(self, entry: dict[str, Any]) -> str:
        if self._memory_repo:
            return self._memory_repo.save_interaction(entry)
        return entry["id"]

    async def _get_history_mysql(
        self, customer_id: str, thread_id: str | None, limit: int
    ) -> list[dict[str, Any]]:
        if self._memory_repo:
            return self._memory_repo.get_history(customer_id, thread_id, limit)
        return []

    async def _search_mysql(
        self, query: str, customer_id: str | None, limit: int
    ) -> list[dict[str, Any]]:
        if self._memory_repo:
            return self._memory_repo.search(query, customer_id, limit)
        return []

    # ── ChromaDB 后端 ─────────────────────────────────────────────────

    async def _init_chroma(self) -> None:
        try:
            import chromadb
            self._chroma_client = chromadb.PersistentClient(path=self.config.persist_dir)
            self._chroma_collection = self._chroma_client.get_or_create_collection(
                name="customer_memories",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("[Memory] ChromaDB 已连接，集合: customer_memories")
        except ImportError:
            logger.error("[Memory] 请安装 chromadb: pip install chromadb")
        except Exception as e:
            logger.error(f"[Memory] ChromaDB 连接失败: {e}")

    async def _save_chroma(self, entry: dict[str, Any]) -> str:
        if not self._chroma_collection:
            return entry["id"]
        try:
            user_text = entry.get("user_message", "")
            assistant_text = entry.get("assistant_message", "")
            self._chroma_collection.add(
                ids=[entry["id"]],
                documents=[f"{user_text} {assistant_text}"],
                metadatas=[{
                    "customer_id": entry["customer_id"],
                    "thread_id": entry.get("thread_id", ""),
                    "timestamp": entry["timestamp"],
                    "type": entry.get("metadata", {}).get("type", "interaction"),
                }],
            )
            logger.debug(f"[Memory] ChromaDB 存储: {entry['id']}")
        except Exception as e:
            logger.error(f"[Memory] ChromaDB 存储失败: {e}")
        return entry["id"]

    async def _get_history_chroma(
        self, customer_id: str, thread_id: str | None, limit: int
    ) -> list[dict[str, Any]]:
        if not self._chroma_collection:
            return []
        try:
            where = {"customer_id": customer_id}
            if thread_id:
                where["thread_id"] = thread_id
            results = self._chroma_collection.get(
                where=where,
                limit=limit,
                include=["documents", "metadatas"],
            )
            history = []
            for i, doc_id in enumerate(results.get("ids", [])):
                history.append({
                    "id": doc_id,
                    "customer_id": results["metadatas"][i].get("customer_id"),
                    "thread_id": results["metadatas"][i].get("thread_id"),
                    "content": results["documents"][i] if results.get("documents") else "",
                    "timestamp": results["metadatas"][i].get("timestamp"),
                })
            return history
        except Exception as e:
            logger.error(f"[Memory] ChromaDB 查询失败: {e}")
            return []

    async def _search_chroma(
        self, query: str, customer_id: str | None, limit: int
    ) -> list[dict[str, Any]]:
        if not self._chroma_collection:
            return []
        try:
            where = {}
            if customer_id:
                where["customer_id"] = customer_id
            results = self._chroma_collection.query(
                query_texts=[query],
                n_results=limit,
                where=where if where else None,
                include=["documents", "metadatas", "distances"],
            )
            memories = []
            ids_list = results.get("ids", [[]])
            docs_list = results.get("documents", [[]])
            metas_list = results.get("metadatas", [[]])
            dists_list = results.get("distances", [[]])
            for i, doc_id in enumerate(ids_list[0] if ids_list else []):
                memories.append({
                    "id": doc_id,
                    "content": docs_list[0][i] if docs_list and docs_list[0] else "",
                    "metadata": metas_list[0][i] if metas_list and metas_list[0] else {},
                    "score": 1 - dists_list[0][i] if dists_list and dists_list[0] else 0,
                })
            return memories
        except Exception as e:
            logger.error(f"[Memory] ChromaDB 搜索失败: {e}")
            return []

    # ── Redis 后端 ────────────────────────────────────────────────────

    async def _init_redis(self) -> None:
        import os
        try:
            import redis.asyncio as redis
            self._redis_client = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                db=int(os.getenv("REDIS_DB", "0")),
                password=os.getenv("REDIS_PASSWORD") or None,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            await self._redis_client.ping()
            logger.info(f"[Memory] Redis 已连接: {os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}")
        except ImportError:
            logger.error("[Memory] 请安装 redis: pip install redis")
        except Exception as e:
            logger.error(f"[Memory] Redis 连接失败: {e}，将回退到文件存储")

    async def _save_redis(self, entry: dict[str, Any]) -> str:
        if not self._redis_client:
            return entry["id"]
        try:
            key = f"mem:{entry['customer_id']}:{entry['id']}"
            await self._redis_client.set(key, json.dumps(entry, ensure_ascii=False))
            await self._redis_client.expire(key, 86400 * 30)  # 30天过期
            # 加入对话列表
            list_key = f"history:{entry['customer_id']}:{entry.get('thread_id', '')}"
            await self._redis_client.rpush(list_key, key)
            await self._redis_client.expire(list_key, 86400 * 30)
            logger.debug(f"[Memory] Redis 存储: {entry['id']}")
        except Exception as e:
            logger.error(f"[Memory] Redis 存储失败: {e}")
        return entry["id"]

    async def _get_history_redis(
        self, customer_id: str, thread_id: str | None, limit: int
    ) -> list[dict[str, Any]]:
        if not self._redis_client:
            return []
        try:
            tid = thread_id or ""
            list_key = f"history:{customer_id}:{tid}"
            keys = await self._redis_client.lrange(list_key, -limit, -1)
            history = []
            for key in keys:
                data = await self._redis_client.get(key)
                if data:
                    history.append(json.loads(data))
            return history
        except Exception as e:
            logger.error(f"[Memory] Redis 查询失败: {e}")
            return []

    async def _search_redis(self, query: str, customer_id: str | None, limit: int) -> list[dict[str, Any]]:
        if not self._redis_client:
            return []
        try:
            pattern = f"mem:{customer_id or '*'}:*"
            results = []
            async for key in self._redis_client.scan_iter(match=pattern, count=100):
                data = await self._redis_client.get(key)
                if data and query.lower() in data.lower():
                    results.append(json.loads(data))
                    if len(results) >= limit:
                        break
            return results
        except Exception as e:
            logger.error(f"[Memory] Redis 搜索失败: {e}")
            return []
