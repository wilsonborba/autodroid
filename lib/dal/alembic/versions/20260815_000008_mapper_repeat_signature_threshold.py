"""add mapper_sessions.repeat_signature_threshold for scroll repetition cutoff

Revision ID: 20260815_000008
Revises: 20260815_000007
Create Date: 2026-08-15 23:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260815_000008"
down_revision = "20260815_000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mapper_sessions", sa.Column("repeat_signature_threshold", sa.Integer(), nullable=False, server_default="20"))


def downgrade() -> None:
    op.drop_column("mapper_sessions", "repeat_signature_threshold")
