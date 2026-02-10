"""Add settings and task_runs tables.

Revision ID: 005
Revises: 004_add_grouped_id_to_posts
Create Date: 2026-01-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


# Default settings values
DEFAULT_SETTINGS = [
    {
        "key": "ranking.post_limit",
        "value": 50000,
        "description": "Maximum posts to rank per period (prevents memory issues)",
    },
    {
        "key": "ranking.novelty_weight",
        "value": 5.0,
        "description": "Weight for novelty score in v3/v4 formulas (3=balanced, 5=default, 7-10=novelty-focused)",
    },
    {
        "key": "ranking.avg_posts_per_day",
        "value": 5.0,
        "description": "Baseline for frequency penalty in v4 formula",
    },
    {
        "key": "collector.fetch_window_days",
        "value": 1,
        "description": "Default window for regular post collection (days)",
    },
    {
        "key": "collector.deep_fetch_days",
        "value": 7,
        "description": "Window for deep fetch (days)",
    },
    {
        "key": "novelty.context_days",
        "value": 30,
        "description": "Days of posts to use as context for novelty analysis",
    },
    {
        "key": "novelty.batch_limit",
        "value": 20,
        "description": "Max posts to analyze for novelty per batch",
    },
]


def upgrade() -> None:
    # Create settings table
    op.create_table(
        "settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(100), nullable=True),
    )

    # Create task_runs table
    op.create_table(
        "task_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("task_name", sa.String(100), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("input_params", JSONB, nullable=True),
        sa.Column("result_summary", JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
    )

    # Create indexes for task_runs
    op.create_index(
        "ix_task_runs_task_started",
        "task_runs",
        ["task_name", "started_at"],
    )
    op.create_index("ix_task_runs_status", "task_runs", ["status"])
    op.create_index("ix_task_runs_started_at", "task_runs", ["started_at"])

    # Insert default settings
    settings_table = sa.table(
        "settings",
        sa.column("key", sa.String),
        sa.column("value", JSONB),
        sa.column("description", sa.String),
    )

    for setting in DEFAULT_SETTINGS:
        op.execute(
            settings_table.insert().values(
                key=setting["key"],
                value=setting["value"],
                description=setting["description"],
            )
        )


def downgrade() -> None:
    op.drop_index("ix_task_runs_started_at", table_name="task_runs")
    op.drop_index("ix_task_runs_status", table_name="task_runs")
    op.drop_index("ix_task_runs_task_started", table_name="task_runs")
    op.drop_table("task_runs")
    op.drop_table("settings")
