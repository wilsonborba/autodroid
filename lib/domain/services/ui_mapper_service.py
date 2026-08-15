from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lib.core.settings import Settings
from lib.core.utils.clock import utc_now
from lib.dal.local.database import session_scope
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.dal.remote.adb_adapter import AdbAdapter
from lib.dal.remote.uiautomator_adapter import UiAutomatorAdapter
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode, MapperRunConfig, MapperSessionStatus
from lib.domain.services.mapper_engine import MapperEngine
from lib.domain.services.mapper_fingerprint_service import MapperFingerprintService
from lib.domain.services.mapper_mode_service import MapperModeService
from lib.domain.services.navigation_context_service import NavigationContextService


@dataclass
class MapperActionCandidate:
    action_key: str
    label: str | None
    bounds: str | None
    node: dict[str, Any]


class UiMapperService(MapperEngine):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.adb = AdbAdapter(settings.android_serial)
        self.ui = UiAutomatorAdapter(settings.android_serial)
        self.navigation_context = NavigationContextService(self.adb)
        self.mode_service = MapperModeService()
        self.fingerprint_service = MapperFingerprintService()

    def run(self, config: MapperRunConfig) -> dict[str, Any]:
        limits = self.mode_service.get_limits(config.mode)
        self.navigation_context.prepare_fresh_app_launch(config.package_name)

        with session_scope() as session:
            repository = SqlAlchemyMapperRepository(session)
            mapper_session = repository.create_session(
                package_name=config.package_name,
                mode=config.mode,
                skip_dangerous_actions=config.skip_dangerous_actions,
                max_depth=limits.max_depth,
                max_actions=limits.max_actions,
                max_scrolls=limits.max_scrolls,
                metadata_json={"mode": config.mode.value},
            )
            mapper_session.status = MapperSessionStatus.RUNNING
            mapper_session.started_at = utc_now()

            state = {"actions_executed": 0, "screens_recorded": 0, "scrolls_used": 0, "revisited_screens": 0}
            self._explore(repository, mapper_session.id, depth=0, state=state, max_depth=limits.max_depth, max_actions=limits.max_actions, max_scrolls=limits.max_scrolls)

            mapper_session.status = MapperSessionStatus.COMPLETED
            mapper_session.finished_at = utc_now()
            return {
                "session_id": mapper_session.id,
                "package_name": mapper_session.package_name,
                "mode": mapper_session.mode.value,
                "screens_recorded": state["screens_recorded"],
                "actions_executed": state["actions_executed"],
                "scrolls_used": state["scrolls_used"],
                "revisited_screens": state["revisited_screens"],
                "status": mapper_session.status.value,
            }

    def _explore(self, repository: SqlAlchemyMapperRepository, session_id: int, *, depth: int, state: dict[str, int], max_depth: int, max_actions: int, max_scrolls: int) -> int | None:
        nodes = self.ui.dump_nodes()
        fingerprint = self.fingerprint_service.fingerprint(nodes)
        existing_screen = repository.find_screen_by_fingerprint(session_id, fingerprint)
        if existing_screen is not None:
            repository.increment_screen_visit_count(existing_screen.id)
            state["revisited_screens"] += 1
            return existing_screen.id

        screen = repository.create_screen(
            session_id=session_id,
            fingerprint=fingerprint,
            screen_key=f"screen-{state['screens_recorded'] + 1}",
            depth=depth,
            ordinal=state["screens_recorded"],
            metadata_json={"node_count": len(nodes)},
        )
        state["screens_recorded"] += 1

        persisted_nodes = []
        for index, node in enumerate(nodes):
            persisted_nodes.append(
                repository.create_node(
                    screen_id=screen.id,
                    node_key=self._node_key(node, index),
                    text=node.get("text"),
                    content_desc=node.get("content_desc"),
                    resource_id=node.get("resource_id"),
                    class_name=node.get("class_name"),
                    bounds=node.get("bounds"),
                    clickable=bool(node.get("clickable", False)),
                    enabled=bool(node.get("enabled", True)),
                    checkable=bool(node.get("checkable", False)),
                    checked=bool(node.get("checked", False)),
                    focusable=bool(node.get("focusable", False)),
                    scrollable=bool(node.get("scrollable", False)),
                    long_clickable=bool(node.get("long_clickable", False)),
                    package_name=node.get("package_name"),
                )
            )

        if depth >= max_depth:
            return screen.id

        candidates = self._extract_candidates(nodes)
        for index, candidate in enumerate(candidates):
            if state["actions_executed"] >= max_actions:
                break
            node_id = persisted_nodes[index].id if index < len(persisted_nodes) else None
            action = repository.create_action(
                session_id=session_id,
                screen_id=screen.id,
                node_id=node_id,
                action_key=candidate.action_key,
                action_type="click",
                label=candidate.label,
                safety=MapperActionSafety.SAFE,
                executed=False,
            )
            if not candidate.bounds:
                action.skipped_reason = "missing_bounds"
                continue
            success = self.ui.click_bounds(candidate.bounds)
            action.executed = True
            action.success = success
            state["actions_executed"] += 1
            if success:
                to_screen_id = self._explore(repository, session_id, depth=depth + 1, state=state, max_depth=max_depth, max_actions=max_actions, max_scrolls=0)
                repository.create_transition(
                    session_id=session_id,
                    from_screen_id=screen.id,
                    action_id=action.id,
                    to_screen_id=to_screen_id,
                    result_type="clicked",
                )
                self.adb.press_back()
            else:
                repository.create_transition(
                    session_id=session_id,
                    from_screen_id=screen.id,
                    action_id=action.id,
                    to_screen_id=None,
                    result_type="failed_click",
                )

        if max_scrolls > 0 and state["scrolls_used"] < max_scrolls:
            self.ui.swipe_up()
            state["scrolls_used"] += 1
            self._explore(repository, session_id, depth=depth, state=state, max_depth=max_depth, max_actions=max_actions, max_scrolls=0)

        return screen.id

    def _extract_candidates(self, nodes: list[dict[str, Any]]) -> list[MapperActionCandidate]:
        candidates: list[MapperActionCandidate] = []
        for index, node in enumerate(nodes):
            label = str(node.get("text") or node.get("content_desc") or "").strip() or None
            if not node.get("clickable"):
                continue
            if not label and not node.get("resource_id"):
                continue
            candidates.append(
                MapperActionCandidate(
                    action_key=f"click:{index}:{node.get('resource_id') or label or node.get('bounds')}",
                    label=label,
                    bounds=node.get("bounds"),
                    node=node,
                )
            )
        return candidates

    def _node_key(self, node: dict[str, Any], index: int) -> str:
        return f"{index}:{node.get('resource_id') or ''}:{node.get('text') or ''}:{node.get('content_desc') or ''}:{node.get('bounds') or ''}"
