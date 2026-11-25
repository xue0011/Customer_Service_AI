"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-30

使用 Base.metadata.create_all 一次性建表，与 ORM 模型保持单一事实来源。
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from src.database.models import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from src.database.models import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
