from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lib.core.utils.clock import utc_now
from lib.dal.local.database import Base
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode, MapperSessionStatus


class MapperSession(Base):
    __tablename__ = "mapper_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_name: Mapped[str] = mapped_column(String(160), nullable=False)
    mode: Mapped[MapperMode] = mapped_column(SqlEnum(MapperMode, name="mapper_mode"), nullable=False)
    status: Mapped[MapperSessionStatus] = mapped_column(SqlEnum(MapperSessionStatus, name="mapper_session_status"), nullable=False, default=MapperSessionStatus.PENDING)
    skip_dangerous_actions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    max_actions: Mapped[int] = mapped_column(Integer, nullable=False)
    max_scrolls: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    screens: Mapped[list[MapperScreen]] = relationship(back_populates="session", cascade="all, delete-orphan")
    actions: Mapped[list[MapperAction]] = relationship(back_populates="session", cascade="all, delete-orphan")
    transitions: Mapped[list[MapperTransition]] = relationship(back_populates="session", cascade="all, delete-orphan")


class MapperScreen(Base):
    __tablename__ = "mapper_screens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("mapper_sessions.id", ondelete="CASCADE"), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    screen_key: Mapped[str] = mapped_column(String(160), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    screenshot_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_hierarchy_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    visit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    session: Mapped[MapperSession] = relationship(back_populates="screens")
    nodes: Mapped[list[MapperNode]] = relationship(back_populates="screen", cascade="all, delete-orphan")


class MapperNode(Base):
    __tablename__ = "mapper_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    screen_id: Mapped[int] = mapped_column(ForeignKey("mapper_screens.id", ondelete="CASCADE"), nullable=False)
    node_key: Mapped[str] = mapped_column(String(256), nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_desc: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    class_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bounds: Mapped[str | None] = mapped_column(String(80), nullable=True)
    clickable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    checkable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    focusable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scrollable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    long_clickable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    package_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    extra_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    screen: Mapped[MapperScreen] = relationship(back_populates="nodes")


class MapperAction(Base):
    __tablename__ = "mapper_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("mapper_sessions.id", ondelete="CASCADE"), nullable=False)
    screen_id: Mapped[int] = mapped_column(ForeignKey("mapper_screens.id", ondelete="CASCADE"), nullable=False)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("mapper_nodes.id", ondelete="SET NULL"), nullable=True)
    action_key: Mapped[str] = mapped_column(String(255), nullable=False)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    safety: Mapped[MapperActionSafety] = mapped_column(SqlEnum(MapperActionSafety, name="mapper_action_safety"), nullable=False)
    skipped_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    session: Mapped[MapperSession] = relationship(back_populates="actions")


class MapperTransition(Base):
    __tablename__ = "mapper_transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("mapper_sessions.id", ondelete="CASCADE"), nullable=False)
    from_screen_id: Mapped[int] = mapped_column(ForeignKey("mapper_screens.id", ondelete="CASCADE"), nullable=False)
    action_id: Mapped[int] = mapped_column(ForeignKey("mapper_actions.id", ondelete="CASCADE"), nullable=False)
    to_screen_id: Mapped[int | None] = mapped_column(ForeignKey("mapper_screens.id", ondelete="SET NULL"), nullable=True)
    result_type: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    session: Mapped[MapperSession] = relationship(back_populates="transitions")
