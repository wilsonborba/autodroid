"""add mapper models

Revision ID: 20260815_000002
Revises: 20260814_000001
Create Date: 2026-08-15 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260815_000002"
down_revision = "20260814_000001"
branch_labels = None
depends_on = None

mapper_mode_enum = sa.Enum("light", "medium", "deep", name="mapper_mode")
mapper_session_status_enum = sa.Enum("pending", "running", "completed", "failed", "cancelled", name="mapper_session_status")
mapper_action_safety_enum = sa.Enum("safe", "dangerous", name="mapper_action_safety")


def upgrade() -> None:
    bind = op.get_bind()
    mapper_mode_enum.create(bind, checkfirst=True)
    mapper_session_status_enum.create(bind, checkfirst=True)
    mapper_action_safety_enum.create(bind, checkfirst=True)

    op.create_table(
        "mapper_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("package_name", sa.String(length=160), nullable=False),
        sa.Column("mode", mapper_mode_enum, nullable=False),
        sa.Column("status", mapper_session_status_enum, nullable=False, server_default="pending"),
        sa.Column("skip_dangerous_actions", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("max_depth", sa.Integer(), nullable=False),
        sa.Column("max_actions", sa.Integer(), nullable=False),
        sa.Column("max_scrolls", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_mapper_sessions_package_name_created_at", "mapper_sessions", ["package_name", "created_at"])

    op.create_table(
        "mapper_screens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("mapper_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("screen_key", sa.String(length=160), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("screenshot_path", sa.String(length=512), nullable=True),
        sa.Column("raw_hierarchy_path", sa.String(length=512), nullable=True),
        sa.Column("visit_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_mapper_screens_session_id_fingerprint", "mapper_screens", ["session_id", "fingerprint"], unique=False)

    op.create_table(
        "mapper_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("screen_id", sa.Integer(), sa.ForeignKey("mapper_screens.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_key", sa.String(length=256), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("content_desc", sa.Text(), nullable=True),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("class_name", sa.String(length=255), nullable=True),
        sa.Column("bounds", sa.String(length=80), nullable=True),
        sa.Column("clickable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("checkable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("focusable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scrollable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("long_clickable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("package_name", sa.String(length=160), nullable=True),
        sa.Column("extra_json", sa.JSON(), nullable=True),
    )

    op.create_table(
        "mapper_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("mapper_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("screen_id", sa.Integer(), sa.ForeignKey("mapper_screens.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("mapper_nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action_key", sa.String(length=255), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("safety", mapper_action_safety_enum, nullable=False),
        sa.Column("skipped_reason", sa.Text(), nullable=True),
        sa.Column("executed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_mapper_actions_session_id_screen_id", "mapper_actions", ["session_id", "screen_id"])

    op.create_table(
        "mapper_transitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("mapper_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_screen_id", sa.Integer(), sa.ForeignKey("mapper_screens.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("mapper_actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_screen_id", sa.Integer(), sa.ForeignKey("mapper_screens.id", ondelete="SET NULL"), nullable=True),
        sa.Column("result_type", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("mapper_transitions")
    op.drop_index("ix_mapper_actions_session_id_screen_id", table_name="mapper_actions")
    op.drop_table("mapper_actions")
    op.drop_table("mapper_nodes")
    op.drop_index("ix_mapper_screens_session_id_fingerprint", table_name="mapper_screens")
    op.drop_table("mapper_screens")
    op.drop_index("ix_mapper_sessions_package_name_created_at", table_name="mapper_sessions")
    op.drop_table("mapper_sessions")

    bind = op.get_bind()
    mapper_action_safety_enum.drop(bind, checkfirst=True)
    mapper_session_status_enum.drop(bind, checkfirst=True)
    mapper_mode_enum.drop(bind, checkfirst=True)
