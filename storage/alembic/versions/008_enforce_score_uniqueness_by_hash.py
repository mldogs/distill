"""Enforce Score uniqueness by period_hash and deduplicate existing rows.

Revision ID: 008
Revises: 007
Create Date: 2026-01-13

This migration:
1. Deduplicates existing Score rows by (post_id, formula_version, period_hash)
2. Drops old unique constraint (post_id, formula_version, period_start, period_end)
3. Creates new unique constraint (post_id, formula_version, period_hash)
4. Creates composite index for fast period_hash lookup

Note: period_hash must be populated (run backfill script first) before running this migration.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Deduplicate existing scores
    # Keep the most recent score (highest computed_at) for each (post_id, formula_version, period_hash) group
    print("Deduplicating existing Score records...")

    dedupe_query = text("""
        DELETE FROM scores
        WHERE id IN (
            SELECT id FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY post_id, formula_version, period_hash
                        ORDER BY computed_at DESC, score DESC
                    ) as rn
                FROM scores
                WHERE period_hash IS NOT NULL
            ) ranked
            WHERE rn > 1
        )
    """)

    result = conn.execute(dedupe_query)
    deleted_count = result.rowcount
    print(f"Deleted {deleted_count} duplicate Score records")

    # Step 2: Drop old unique constraint
    print("Dropping old unique constraint uq_score_post_formula_period...")
    op.drop_constraint("uq_score_post_formula_period", "scores", type_="unique")

    # Step 3: Create new unique constraint on period_hash
    print("Creating new unique constraint uq_score_post_formula_hash...")
    op.create_unique_constraint(
        "uq_score_post_formula_hash",
        "scores",
        ["post_id", "formula_version", "period_hash"],
    )

    # Step 4: Create composite index for fast lookup
    print("Creating composite index ix_scores_formula_hash_score...")
    op.create_index(
        "ix_scores_formula_hash_score",
        "scores",
        ["formula_version", "period_hash", sa.text("score DESC")],
    )

    print("Migration 008 complete!")


def downgrade() -> None:
    # Drop new constraint and index
    op.drop_index("ix_scores_formula_hash_score", table_name="scores")
    op.drop_constraint("uq_score_post_formula_hash", "scores", type_="unique")

    # Recreate old constraint
    op.create_unique_constraint(
        "uq_score_post_formula_period",
        "scores",
        ["post_id", "formula_version", "period_start", "period_end"],
    )
