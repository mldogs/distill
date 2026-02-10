"""add_fts_search_vector

Revision ID: a1b2c3d4e5f6
Revises: bff5f0c20b7c
Create Date: 2026-02-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add generated tsvector column for full-text search
    op.execute(
        """
        ALTER TABLE posts
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('russian', coalesce(text, ''))) STORED
        """
    )

    # Create GIN index concurrently (requires autocommit)
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_posts_search_vector "
            "ON posts USING gin(search_vector)"
        )


def downgrade() -> None:
    op.drop_index("ix_posts_search_vector", table_name="posts")
    op.drop_column("posts", "search_vector")
