"""add mapper route/transition performance tables for the flow route planner

Revision ID: 20260815_000007
Revises: 20260815_000006
Create Date: 2026-08-15 22:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260815_000007"
down_revision = "20260815_000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mapper_transition_performance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transition_id", sa.Integer(), sa.ForeignKey("mapper_transitions.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mean_duration_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ewma_duration_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_duration_ms", sa.Float(), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "mapper_route_performance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("from_screen_id", sa.Integer(), sa.ForeignKey("mapper_screens.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_screen_id", sa.Integer(), sa.ForeignKey("mapper_screens.id", ondelete="CASCADE"), nullable=False),
        sa.Column("strategy_type", sa.String(length=40), nullable=False),
        sa.Column("route_signature", sa.String(length=128), nullable=False, unique=True),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mean_duration_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ewma_duration_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_duration_ms", sa.Float(), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mapper_route_performance_from_to", "mapper_route_performance", ["from_screen_id", "to_screen_id"])


def downgrade() -> None:
    op.drop_index("ix_mapper_route_performance_from_to", table_name="mapper_route_performance")
    op.drop_table("mapper_route_performance")
    op.drop_table("mapper_transition_performance")
