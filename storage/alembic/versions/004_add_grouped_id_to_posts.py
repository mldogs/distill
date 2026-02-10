"""add grouped_id to posts for album support

Revision ID: 004
Revises: bff5f0c20b7c
Create Date: 2026-01-12 13:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = 'bff5f0c20b7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add grouped_id column for Telegram album grouping
    op.add_column('posts', sa.Column('grouped_id', sa.BigInteger(), nullable=True))
    op.create_index('ix_posts_grouped_id', 'posts', ['channel_id', 'grouped_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_posts_grouped_id', table_name='posts')
    op.drop_column('posts', 'grouped_id')
