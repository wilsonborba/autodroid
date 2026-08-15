"""add mapper checkpoint columns for incremental remap

Revision ID: 20260815_000004
Revises: 20260815_000003
Create Date: 2026-08-15 18:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260815_000004"
down_revision = "20260815_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mapper_sessions", sa.Column("explored_up_to_depth", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("mapper_screens", sa.Column("expanded", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("mapper_screens", "expanded")
    op.drop_column("mapper_sessions", "explored_up_to_depth")
