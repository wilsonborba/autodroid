"""add mapper flow models

Revision ID: 20260815_000003
Revises: 20260815_000002
Create Date: 2026-08-15 15:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260815_000003"
down_revision = "20260815_000002"
branch_labels = None
depends_on = None

mapper_action_safety_enum = sa.Enum("safe", "dangerous", name="mapper_action_safety")


def upgrade() -> None:
    bind = op.get_bind()
    mapper_action_safety_enum.create(bind, checkfirst=True)

    op.create_table(
        "mapper_flows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("package_name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_session_id", sa.Integer(), sa.ForeignKey("mapper_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.UniqueConstraint("package_name", "name", name="uq_mapper_flow_package_name"),
    )

    op.create_table(
        "mapper_flow_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flow_id", sa.Integer(), sa.ForeignKey("mapper_flows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("selector_json", sa.JSON(), nullable=False),
        sa.Column("safety", mapper_action_safety_enum, nullable=False, server_default="safe"),
        sa.Column("source_screen_id", sa.Integer(), sa.ForeignKey("mapper_screens.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_action_id", sa.Integer(), sa.ForeignKey("mapper_actions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("params_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_mapper_flow_steps_flow_id_ordinal", "mapper_flow_steps", ["flow_id", "ordinal"])


def downgrade() -> None:
    op.drop_index("ix_mapper_flow_steps_flow_id_ordinal", table_name="mapper_flow_steps")
    op.drop_table("mapper_flow_steps")
    op.drop_table("mapper_flows")
