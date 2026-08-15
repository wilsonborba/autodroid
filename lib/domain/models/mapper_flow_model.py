from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lib.core.utils.clock import utc_now
from lib.dal.local.database import Base
from lib.domain.models.mapper_types import MapperActionSafety


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

    steps: Mapped[list[MapperFlowStep]] = relationship(back_populates="flow", cascade="all, delete-orphan", order_by="MapperFlowStep.ordinal")


class MapperFlowStep(Base):
    __tablename__ = "mapper_flow_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flow_id: Mapped[int] = mapped_column(ForeignKey("mapper_flows.id", ondelete="CASCADE"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    selector_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    safety: Mapped[MapperActionSafety] = mapped_column(SqlEnum(MapperActionSafety, name="mapper_action_safety"), nullable=False, default=MapperActionSafety.SAFE)
    source_screen_id: Mapped[int | None] = mapped_column(ForeignKey("mapper_screens.id", ondelete="SET NULL"), nullable=True)
    source_action_id: Mapped[int | None] = mapped_column(ForeignKey("mapper_actions.id", ondelete="SET NULL"), nullable=True)
    params_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    flow: Mapped[MapperFlow] = relationship(back_populates="steps")
