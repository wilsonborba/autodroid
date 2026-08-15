from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from lib.core.utils.clock import utc_now
from lib.dal.local.database import Base


class MapperTransitionPerformance(Base):
    """Observed runtime cost of a single `MapperTransition` (issue #24). Deliberately separate
    from `MapperTransition`, which keeps representing map topology only, never a live metric.
    This is learned planner state, not a general execution log (see #18/#21): only real,
    measured observations land here, never estimates."""

    __tablename__ = "mapper_transition_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transition_id: Mapped[int] = mapped_column(ForeignKey("mapper_transitions.id", ondelete="CASCADE"), nullable=False, unique=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mean_duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ewma_duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class MapperRoutePerformance(Base):
    """Observed runtime cost of a *whole* route between two screens (issue #24), one strategy
    at a time (`direct_path` for a specific `route_signature`, or `restart`). Kept separate from
    per-transition performance because summed edge duration doesn't necessarily match real route
    duration (animations, wait overlap, screen readiness, ...)."""

    __tablename__ = "mapper_route_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_screen_id: Mapped[int] = mapped_column(ForeignKey("mapper_screens.id", ondelete="CASCADE"), nullable=False)
    to_screen_id: Mapped[int] = mapped_column(ForeignKey("mapper_screens.id", ondelete="CASCADE"), nullable=False)
    strategy_type: Mapped[str] = mapped_column(String(40), nullable=False)
    route_signature: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mean_duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ewma_duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
