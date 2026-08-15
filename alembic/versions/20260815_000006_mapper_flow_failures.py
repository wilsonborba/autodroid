"""add mapper flow failures table

Revision ID: 20260815_000006
Revises: 20260815_000005
Create Date: 2026-08-15 21:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260815_000006"
down_revision = "20260815_000005"
branch_labels = None
depends_on = None

mapper_flow_failure_type_enum = sa.Enum(
    "selector_not_found", "click_failed", "unsupported_action_type", "exception",
    name="mapper_flow_failure_type",
)


def upgrade() -> None:
    bind = op.get_bind()
    mapper_flow_failure_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "mapper_flow_failures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flow_id", sa.Integer(), sa.ForeignKey("mapper_flows.id", ondelete="SET NULL"), nullable=True),
        sa.Column("step_id", sa.Integer(), sa.ForeignKey("mapper_flow_steps.id", ondelete="SET NULL"), nullable=True),
        sa.Column("package_name", sa.String(length=160), nullable=False),
        sa.Column("failure_type", mapper_flow_failure_type_enum, nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mapper_flow_failures_package_name_resolved_at", "mapper_flow_failures", ["package_name", "resolved_at"])


def downgrade() -> None:
    op.drop_index("ix_mapper_flow_failures_package_name_resolved_at", table_name="mapper_flow_failures")
    op.drop_table("mapper_flow_failures")

    bind = op.get_bind()
    mapper_flow_failure_type_enum.drop(bind, checkfirst=True)
