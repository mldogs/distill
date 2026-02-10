"""add_post_embeddings

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-09 12:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create post_embeddings table
    op.create_table(
        "post_embeddings",
        sa.Column("post_id", sa.BigInteger(), sa.ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("model", sa.String(100), nullable=False, server_default="baai/bge-m3"),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_post_embeddings_model", "post_embeddings", ["model"])
    op.create_index("ix_post_embeddings_text_hash", "post_embeddings", ["text_hash"])


def downgrade() -> None:
    op.drop_index("ix_post_embeddings_text_hash", table_name="post_embeddings")
    op.drop_index("ix_post_embeddings_model", table_name="post_embeddings")
    op.drop_table("post_embeddings")
    op.execute("DROP EXTENSION IF EXISTS vector")
