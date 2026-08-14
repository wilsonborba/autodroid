from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from lib.core.utils.clock import utc_now
from lib.dal.local.database import Base


class WorkerStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    DISABLED = "disabled"


class WorkerState(Base):
    __tablename__ = "worker_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worker_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    status: Mapped[WorkerStatus] = mapped_column(SqlEnum(WorkerStatus, name="worker_status"), nullable=False, default=WorkerStatus.IDLE)
    current_job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    execution_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
