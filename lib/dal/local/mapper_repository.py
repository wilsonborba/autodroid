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
        max_consecutive_empty_scrolls: int = 3,
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
            max_consecutive_empty_scrolls=max_consecutive_empty_scrolls,
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
        structural_signature: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> MapperScreen:
        screen = MapperScreen(
            session_id=session_id,
            fingerprint=fingerprint,
            structural_signature=structural_signature if structural_signature is not None else fingerprint,
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
        stmt = select(MapperSession).options(selectinload(MapperSession.screens).selectinload(MapperScreen.nodes), selectinload(MapperSession.actions), selectinload(MapperSession.transitions)).where(MapperSession.id == session_id)
        return self.session.scalar(stmt)

    def list_sessions(self, limit: int = 50) -> list[MapperSession]:
        stmt = select(MapperSession).order_by(MapperSession.created_at.desc()).limit(limit)
        return list(self.session.scalars(stmt))

    def get_latest_session(self, package_name: str, status: MapperSessionStatus | None = None) -> MapperSession | None:
        stmt = (
            select(MapperSession)
            .options(selectinload(MapperSession.screens), selectinload(MapperSession.actions), selectinload(MapperSession.transitions))
            .where(MapperSession.package_name == package_name)
        )
        if status is not None:
            stmt = stmt.where(MapperSession.status == status)
        stmt = stmt.order_by(MapperSession.created_at.desc()).limit(1)
        return self.session.scalar(stmt)

    def find_screen_by_fingerprint(self, session_id: int, fingerprint: str) -> MapperScreen | None:
        stmt = select(MapperScreen).where(MapperScreen.session_id == session_id, MapperScreen.fingerprint == fingerprint)
        return self.session.scalar(stmt)

    def has_other_screen_with_structural_signature(self, session_id: int, structural_signature: str, *, exclude_screen_id: int) -> bool:
        """Issue #30: is this screen another instance of a type already represented in this
        session (e.g. yet another person's profile page)? Checked as soon as a screen is known
        to be brand new, so a chain of same-type screens reached through each other (profile ->
        connections -> profile -> connections -> ...) gets cut after the second one, not after
        the first one's whole subtree finally finishes exploring."""
        stmt = select(MapperScreen.id).where(
            MapperScreen.session_id == session_id,
            MapperScreen.structural_signature == structural_signature,
            MapperScreen.id != exclude_screen_id,
        ).limit(1)
        return self.session.scalar(stmt) is not None


    def increment_screen_visit_count(self, screen_id: int) -> MapperScreen:
        screen = self.session.get(MapperScreen, screen_id)
        if screen is None:
            raise ValueError(f"Mapper screen {screen_id} not found")
        screen.visit_count += 1
        self.session.flush()
        return screen

    def mark_screen_expanded(self, screen_id: int) -> MapperScreen:
        screen = self.session.get(MapperScreen, screen_id)
        if screen is None:
            raise ValueError(f"Mapper screen {screen_id} not found")
        screen.expanded = True
        self.session.flush()
        return screen

    def reset_screen_expanded(self, screen_id: int) -> MapperScreen:
        screen = self.session.get(MapperScreen, screen_id)
        if screen is None:
            raise ValueError(f"Mapper screen {screen_id} not found")
        screen.expanded = False
        self.session.flush()
        return screen

    def find_action_by_key(self, session_id: int, screen_id: int, action_key: str) -> MapperAction | None:
        stmt = select(MapperAction).where(
            MapperAction.session_id == session_id,
            MapperAction.screen_id == screen_id,
            MapperAction.action_key == action_key,
        )
        return self.session.scalar(stmt)

    def get_resumable_session(self, package_name: str) -> MapperSession | None:
        """Most recent session for a package that never reached a terminal status
        (interrupted mid-run: process crashed, device dropped, etc)."""
        stmt = (
            select(MapperSession)
            .options(selectinload(MapperSession.screens), selectinload(MapperSession.actions), selectinload(MapperSession.transitions))
            .where(MapperSession.package_name == package_name, MapperSession.status == MapperSessionStatus.RUNNING)
            .order_by(MapperSession.created_at.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def list_screens(self, session_id: int) -> list[MapperScreen]:
        stmt = (
            select(MapperScreen)
            .where(MapperScreen.session_id == session_id)
            .options(selectinload(MapperScreen.nodes))
            .order_by(MapperScreen.ordinal)
        )
        return list(self.session.scalars(stmt))

    def get_screen(self, screen_id: int) -> MapperScreen | None:
        stmt = select(MapperScreen).where(MapperScreen.id == screen_id).options(selectinload(MapperScreen.nodes))
        return self.session.scalar(stmt)

    def list_actions(
        self,
        session_id: int,
        *,
        screen_id: int | None = None,
        safety: MapperActionSafety | None = None,
        executed: bool | None = None,
    ) -> list[MapperAction]:
        stmt = select(MapperAction).where(MapperAction.session_id == session_id)
        if screen_id is not None:
            stmt = stmt.where(MapperAction.screen_id == screen_id)
        if safety is not None:
            stmt = stmt.where(MapperAction.safety == safety)
        if executed is not None:
            stmt = stmt.where(MapperAction.executed == executed)
        stmt = stmt.order_by(MapperAction.id)
        return list(self.session.scalars(stmt))

    def list_transitions(self, session_id: int) -> list[MapperTransition]:
        stmt = select(MapperTransition).where(MapperTransition.session_id == session_id).order_by(MapperTransition.id)
        return list(self.session.scalars(stmt))

    def get_transition(self, transition_id: int) -> MapperTransition | None:
        return self.session.get(MapperTransition, transition_id)

    def find_transition_to_screen(self, to_screen_id: int) -> MapperTransition | None:
        """The transition that leads into a given screen, used to walk the map backwards
        (issue #23, ancestor-chain resolution). If more than one transition reaches the same
        screen, the earliest recorded one is used, deterministic but otherwise arbitrary."""
        stmt = (
            select(MapperTransition)
            .where(MapperTransition.to_screen_id == to_screen_id, MapperTransition.result_type == "clicked")
            .order_by(MapperTransition.id)
            .limit(1)
        )
        return self.session.scalar(stmt)

    def find_transition_by_action(self, action_id: int) -> MapperTransition | None:
        """The transition produced by a given action, used to know where a step is expected to
        leave the device (issue #24: `MapperFlowStep.source_action_id` -> this -> `to_screen_id`)."""
        stmt = select(MapperTransition).where(MapperTransition.action_id == action_id).order_by(MapperTransition.id).limit(1)
        return self.session.scalar(stmt)

    def get_action(self, action_id: int) -> MapperAction | None:
        return self.session.get(MapperAction, action_id)

    def get_node(self, node_id: int) -> MapperNode | None:
        return self.session.get(MapperNode, node_id)
