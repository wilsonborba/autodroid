"""add jobs.pid to track the subprocess running a job, for force-stop

Revision ID: 20260820_000012
Revises: 20260816_000011
Create Date: 2026-08-20 15:30:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260820_000012"
down_revision = "20260816_000011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("pid", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "pid")
