"""Add period_hash and global_avg_used to scores table.

Revision ID: 007
Revises: 006
Create Date: 2026-01-13

This migration adds:
1. period_hash: String(64) - SHA256 hash for stable period identification
2. global_avg_used: Float - stores global_avg_posts_per_day used in v4 formula
3. Index on period_hash for fast lookup

period_hash is nullable initially for backward compatibility.
Backfill script will populate hashes for existing records.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add period_hash column (nullable for backward compatibility)
    op.add_column(
        "scores",
        sa.Column("period_hash", sa.String(64), nullable=True),
    )

    # Add global_avg_used column for v4 formula reproducibility
    op.add_column(
        "scores",
        sa.Column("global_avg_used", sa.Float(), nullable=True),
    )

    # Create index on period_hash for fast period matching
    op.create_index(
        "ix_scores_period_hash",
        "scores",
        ["period_hash"],
        unique=False,
    )


def downgrade() -> None:
    # Drop index
    op.drop_index("ix_scores_period_hash", table_name="scores")

    # Drop columns
    op.drop_column("scores", "global_avg_used")
    op.drop_column("scores", "period_hash")
