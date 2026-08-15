from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lib.core.utils.clock import utc_now
from lib.dal.local.database import Base
from lib.domain.models.mapper_types import MapperActionSafety, MapperFlowFailureType


class MapperFlow(Base):
    __tablename__ = "mapper_flows"
    __table_args__ = (UniqueConstraint("package_name", "name", name="uq_mapper_flow_package_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    package_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_session_id: Mapped[int | None] = mapped_column(ForeignKey("mapper_sessions.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    step_usages: Mapped[list[MapperFlowStepUsage]] = relationship(
        back_populates="flow", cascade="all, delete-orphan", order_by="MapperFlowStepUsage.ordinal"
    )


class MapperFlowStep(Base):
    """A reusable step definition, scoped to a package_name (not to a single Flow).

    The same step (e.g. "click Profile", born from a specific mapped `source_action_id`) can be
    attached to several Flows through `MapperFlowStepUsage` instead of being redefined per Flow.
    Editing a step here affects every Flow that references it, that's the point of it being a
    shared component instead of an inline, per-Flow definition (issue #23).
    """

    __tablename__ = "mapper_flow_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_name: Mapped[str] = mapped_column(String(160), nullable=False)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    selector_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    safety: Mapped[MapperActionSafety] = mapped_column(SqlEnum(MapperActionSafety, name="mapper_action_safety"), nullable=False, default=MapperActionSafety.SAFE)
    source_screen_id: Mapped[int | None] = mapped_column(ForeignKey("mapper_screens.id", ondelete="SET NULL"), nullable=True)
    source_action_id: Mapped[int | None] = mapped_column(ForeignKey("mapper_actions.id", ondelete="SET NULL"), nullable=True)
    params_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    usages: Mapped[list[MapperFlowStepUsage]] = relationship(back_populates="step", cascade="all, delete-orphan")


class MapperFlowStepUsage(Base):
    """Association between a Flow and a (reusable) step, with the step's position in that Flow."""

    __tablename__ = "mapper_flow_step_usages"
    __table_args__ = (UniqueConstraint("flow_id", "step_id", name="uq_mapper_flow_step_usage"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flow_id: Mapped[int] = mapped_column(ForeignKey("mapper_flows.id", ondelete="CASCADE"), nullable=False)
    step_id: Mapped[int] = mapped_column(ForeignKey("mapper_flow_steps.id", ondelete="CASCADE"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    flow: Mapped[MapperFlow] = relationship(back_populates="step_usages")
    step: Mapped[MapperFlowStep] = relationship(back_populates="usages")


class MapperFlowFailure(Base):
    """An interaction failure (issue #21): the map said one thing, the real app said another.
    Not a log, not an execution-history table (#18 deliberately has neither); this exists only
    to feed the override/complement decision (#19/#20), so only failures are recorded here."""

    __tablename__ = "mapper_flow_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flow_id: Mapped[int | None] = mapped_column(ForeignKey("mapper_flows.id", ondelete="SET NULL"), nullable=True)
    step_id: Mapped[int | None] = mapped_column(ForeignKey("mapper_flow_steps.id", ondelete="SET NULL"), nullable=True)
    package_name: Mapped[str] = mapped_column(String(160), nullable=False)
    failure_type: Mapped[MapperFlowFailureType] = mapped_column(SqlEnum(MapperFlowFailureType, name="mapper_flow_failure_type"), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
