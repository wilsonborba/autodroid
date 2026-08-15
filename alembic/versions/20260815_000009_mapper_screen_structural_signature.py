"""add mapper_screens.structural_signature for cross-instance dedup

Revision ID: 20260815_000009
Revises: 20260815_000008
Create Date: 2026-08-15 23:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260815_000009"
down_revision = "20260815_000008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mapper_screens", sa.Column("structural_signature", sa.String(length=128), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("mapper_screens", "structural_signature")
