from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from lib.domain.models.mapper_model import MapperAction, MapperNode, MapperScreen, MapperSession, MapperTransition
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode, MapperSessionStatus


class SqlAlchemyMapperRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_session(
        self,
        *,
        package_name: str,
        mode: MapperMode,
        skip_dangerous_actions: bool,
        max_depth: int,
        max_actions: int,
        max_scrolls: int,
        metadata_json: dict[str, Any] | None = None,
    ) -> MapperSession:
        mapper_session = MapperSession(
            package_name=package_name,
            mode=mode,
            status=MapperSessionStatus.PENDING,
            skip_dangerous_actions=skip_dangerous_actions,
            max_depth=max_depth,
            max_actions=max_actions,
            max_scrolls=max_scrolls,
            metadata_json=metadata_json,
        )
        self.session.add(mapper_session)
        self.session.flush()
        return mapper_session

    def create_screen(
        self,
        *,
        session_id: int,
        fingerprint: str,
        screen_key: str,
        depth: int,
        ordinal: int,
        metadata_json: dict[str, Any] | None = None,
    ) -> MapperScreen:
        screen = MapperScreen(
            session_id=session_id,
            fingerprint=fingerprint,
            screen_key=screen_key,
            depth=depth,
            ordinal=ordinal,
            metadata_json=metadata_json,
        )
        self.session.add(screen)
        self.session.flush()
        return screen

    def create_node(self, *, screen_id: int, node_key: str, text: str | None = None, content_desc: str | None = None, resource_id: str | None = None, class_name: str | None = None, bounds: str | None = None, clickable: bool = False, enabled: bool = True, checkable: bool = False, checked: bool = False, focusable: bool = False, scrollable: bool = False, long_clickable: bool = False, package_name: str | None = None, extra_json: dict[str, Any] | None = None) -> MapperNode:
        node = MapperNode(screen_id=screen_id, node_key=node_key, text=text, content_desc=content_desc, resource_id=resource_id, class_name=class_name, bounds=bounds, clickable=clickable, enabled=enabled, checkable=checkable, checked=checked, focusable=focusable, scrollable=scrollable, long_clickable=long_clickable, package_name=package_name, extra_json=extra_json)
        self.session.add(node)
        self.session.flush()
        return node

    def create_action(self, *, session_id: int, screen_id: int, node_id: int | None, action_key: str, action_type: str, label: str | None, safety: MapperActionSafety, skipped_reason: str | None = None, executed: bool = False, success: bool | None = None, metadata_json: dict[str, Any] | None = None) -> MapperAction:
        action = MapperAction(session_id=session_id, screen_id=screen_id, node_id=node_id, action_key=action_key, action_type=action_type, label=label, safety=safety, skipped_reason=skipped_reason, executed=executed, success=success, metadata_json=metadata_json)
        self.session.add(action)
        self.session.flush()
        return action

    def create_transition(self, *, session_id: int, from_screen_id: int, action_id: int, to_screen_id: int | None, result_type: str, metadata_json: dict[str, Any] | None = None) -> MapperTransition:
        transition = MapperTransition(session_id=session_id, from_screen_id=from_screen_id, action_id=action_id, to_screen_id=to_screen_id, result_type=result_type, metadata_json=metadata_json)
        self.session.add(transition)
        self.session.flush()
        return transition

    def get_session(self, session_id: int) -> MapperSession | None:
        stmt = select(MapperSession).options(selectinload(MapperSession.screens), selectinload(MapperSession.actions), selectinload(MapperSession.transitions)).where(MapperSession.id == session_id)
        return self.session.scalar(stmt)

    def list_sessions(self, limit: int = 50) -> list[MapperSession]:
        stmt = select(MapperSession).order_by(MapperSession.created_at.desc()).limit(limit)
        return list(self.session.scalars(stmt))

    def find_screen_by_fingerprint(self, session_id: int, fingerprint: str) -> MapperScreen | None:
        stmt = select(MapperScreen).where(MapperScreen.session_id == session_id, MapperScreen.fingerprint == fingerprint)
        return self.session.scalar(stmt)
