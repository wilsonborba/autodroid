"""initial queue models

Revision ID: 20260814_000001
Revises: None
Create Date: 2026-08-14 00:00:01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260814_000001"
down_revision = None
branch_labels = None
depends_on = None

job_status_enum = sa.Enum(
    "pending",
    "scheduled",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
    name="job_status",
)

worker_status_enum = sa.Enum(
    "idle",
    "running",
    "paused",
    "disabled",
    name="worker_status",
)


def upgrade() -> None:
    bind = op.get_bind()
    job_status_enum.create(bind, checkfirst=True)
    worker_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_type", sa.String(length=120), nullable=False),
        sa.Column("adapter_name", sa.String(length=80), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", job_status_enum, nullable=False, server_default="pending"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cron_expression", sa.String(length=80), nullable=True),
        sa.Column("execution_window_start", sa.Time(), nullable=True),
        sa.Column("execution_window_end", sa.Time(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_status_priority_run_after", "jobs", ["status", "priority", "run_after"])

    op.create_table(
        "job_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_events_job_id_created_at", "job_events", ["job_id", "created_at"])

    op.create_table(
        "worker_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_name", sa.String(length=80), nullable=False, unique=True),
        sa.Column("status", worker_status_enum, nullable=False, server_default="idle"),
        sa.Column("current_job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("worker_states")
    op.drop_index("ix_job_events_job_id_created_at", table_name="job_events")
    op.drop_table("job_events")
    op.drop_index("ix_jobs_status_priority_run_after", table_name="jobs")
    op.drop_table("jobs")

    bind = op.get_bind()
    worker_status_enum.drop(bind, checkfirst=True)
    job_status_enum.drop(bind, checkfirst=True)
