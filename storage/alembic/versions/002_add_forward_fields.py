"""Add forward, media, and edit fields to posts

Revision ID: 002
Revises: 001
Create Date: 2026-01-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Forward info — для графа связей между каналами
    op.add_column(
        "posts",
        sa.Column("forwarded_from_channel_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "posts",
        sa.Column("forwarded_from_message_id", sa.BigInteger(), nullable=True),
    )

    # Media type — для фильтрации по типу контента
    op.add_column(
        "posts",
        sa.Column("media_type", sa.String(length=50), nullable=True),
    )

    # Edit date — для трекинга изменений
    op.add_column(
        "posts",
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Индекс для графа связей
    op.create_index(
        "ix_posts_forwarded_from",
        "posts",
        ["forwarded_from_channel_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_posts_forwarded_from", table_name="posts")
    op.drop_column("posts", "edited_at")
    op.drop_column("posts", "media_type")
    op.drop_column("posts", "forwarded_from_message_id")
    op.drop_column("posts", "forwarded_from_channel_id")
