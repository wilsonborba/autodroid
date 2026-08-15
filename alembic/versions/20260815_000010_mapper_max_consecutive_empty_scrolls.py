"""rename mapper_sessions.repeat_signature_threshold to max_consecutive_empty_scrolls

The old column compared whole-viewport structural hashes across scrolls, which rarely repeats
cleanly on a mixed feed. The new one counts consecutive scrolls that found zero new nodes, a
more reliable early-exit signal, used alongside max_scrolls (the hard per-screen ceiling, which
this does not replace, see issue #34).

Revision ID: 20260815_000010
Revises: 20260815_000009
Create Date: 2026-08-15 23:45:00
"""
from __future__ import annotations

from alembic import op

revision = "20260815_000010"
down_revision = "20260815_000009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE mapper_sessions RENAME COLUMN repeat_signature_threshold TO max_consecutive_empty_scrolls")


def downgrade() -> None:
    op.execute("ALTER TABLE mapper_sessions RENAME COLUMN max_consecutive_empty_scrolls TO repeat_signature_threshold")
