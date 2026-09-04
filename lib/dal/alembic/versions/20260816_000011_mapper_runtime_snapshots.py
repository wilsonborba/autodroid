"""add mapper_runtime_snapshots for live churn telemetry

Revision ID: 20260816_000011
Revises: 20260815_000010
Create Date: 2026-08-16 12:30:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260816_000011"
down_revision = "20260815_000010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mapper_runtime_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("mapper_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_name", sa.String(length=160), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("activity_kind", sa.String(length=80), nullable=True),
        sa.Column("current_screen_id", sa.Integer(), nullable=True),
        sa.Column("target_screen_id", sa.Integer(), nullable=True),
        sa.Column("strategy_type", sa.String(length=80), nullable=True),
        sa.Column("route_signature", sa.String(length=255), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("restart_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovery_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revisit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planner_restart_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planner_direct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("known_return_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repeated_route_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repeated_context_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("seconds_since_last_meaningful_progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks_since_last_meaningful_progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_screens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_actions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_transitions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_screens_delta", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_screens_delta", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_delta", sa.Float(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_mapper_runtime_snapshots_session_id", "mapper_runtime_snapshots", ["session_id"])
    op.create_index("ix_mapper_runtime_snapshots_package_name", "mapper_runtime_snapshots", ["package_name"])
    op.create_index("ix_mapper_runtime_snapshots_observed_at", "mapper_runtime_snapshots", ["observed_at"])


def downgrade() -> None:
    op.drop_index("ix_mapper_runtime_snapshots_observed_at", table_name="mapper_runtime_snapshots")
    op.drop_index("ix_mapper_runtime_snapshots_package_name", table_name="mapper_runtime_snapshots")
    op.drop_index("ix_mapper_runtime_snapshots_session_id", table_name="mapper_runtime_snapshots")
    op.drop_table("mapper_runtime_snapshots")
