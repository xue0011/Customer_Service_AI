"""pgvector ANN 索引

Revision ID: 0002_pgvector
Revises: 0001_initial
Create Date: 2026-07-31

在 PostgreSQL 上启用 vector 扩展并为 rag_embeddings 增加向量列 + HNSW 索引，
使检索可走 ANN（retriever 生产路径）。SQLite 等无 vector 扩展时无操作，
继续使用应用层 cosine（兼容测试）。

注意：embedding_vec 维度需与 EmbeddingClient 模型一致（text-embedding-v3 = 1024）。
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_pgvector"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

# 按实际嵌入模型维度调整
EMBEDDING_DIM = 1024


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(
            f"ALTER TABLE rag_embeddings ADD COLUMN IF NOT EXISTS embedding_vec vector({EMBEDDING_DIM})"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_rag_embeddings_vec "
            "ON rag_embeddings USING hnsw (embedding_vec vector_cosine_ops)"
        )
    # 其他方言（SQLite）无 vector 扩展，使用应用层 cosine


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_rag_embeddings_vec")
        op.execute("ALTER TABLE rag_embeddings DROP COLUMN IF EXISTS embedding_vec")
