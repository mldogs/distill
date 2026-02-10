"""Add novelty criteria weights to settings.

Revision ID: 006
Revises: 005
Create Date: 2026-01-13

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


# Default weights for 10 novelty criteria (all equal by default)
CRITERIA_WEIGHTS = [
    {
        "key": "novelty.weight.exclusivity",
        "value": 1.0,
        "description": "Weight for exclusivity criterion (0=widely covered, 0.5=among first, 1=exclusive)",
    },
    {
        "key": "novelty.weight.uniqueness",
        "value": 1.0,
        "description": "Weight for uniqueness criterion (0=common topic, 0.5=known with nuance, 1=rare topic)",
    },
    {
        "key": "novelty.weight.depth",
        "value": 1.0,
        "description": "Weight for depth criterion (0=headline/retell, 0.5=basic overview, 1=detailed analysis)",
    },
    {
        "key": "novelty.weight.perspective",
        "value": 1.0,
        "description": "Weight for perspective criterion (0=conventional view, 0.5=slight twist, 1=unique angle)",
    },
    {
        "key": "novelty.weight.factual",
        "value": 1.0,
        "description": "Weight for factual criterion (0=opinions only, 0.5=mixed, 1=concrete facts)",
    },
    {
        "key": "novelty.weight.data",
        "value": 1.0,
        "description": "Weight for data criterion (0=no data, 0.5=some numbers, 1=statistics/research)",
    },
    {
        "key": "novelty.weight.sources",
        "value": 1.0,
        "description": "Weight for sources criterion (0=no sources, 0.5=secondary, 1=primary sources)",
    },
    {
        "key": "novelty.weight.context",
        "value": 1.0,
        "description": "Weight for context criterion (0=isolated fact, 0.5=partial, 1=full picture)",
    },
    {
        "key": "novelty.weight.actionable",
        "value": 1.0,
        "description": "Weight for actionable criterion (0=abstract, 0.5=general advice, 1=specific actions)",
    },
    {
        "key": "novelty.weight.clarity",
        "value": 1.0,
        "description": "Weight for clarity criterion (0=messy, 0.5=readable, 1=well structured)",
    },
]


def upgrade() -> None:
    settings_table = sa.table(
        "settings",
        sa.column("key", sa.String),
        sa.column("value", JSONB),
        sa.column("description", sa.String),
    )

    for setting in CRITERIA_WEIGHTS:
        op.execute(
            settings_table.insert().values(
                key=setting["key"],
                value=setting["value"],
                description=setting["description"],
            )
        )


def downgrade() -> None:
    for setting in CRITERIA_WEIGHTS:
        op.execute(f"DELETE FROM settings WHERE key = '{setting['key']}'")
