from __future__ import annotations

from typing import Any

from lib.core.settings import Settings
from lib.core.utils.clock import utc_now
from lib.dal.local.database import session_scope
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode, MapperSessionStatus, MapperScreenCompletionState
from lib.domain.services.mapper_churn_service import MapperChurnService
from lib.domain.services.ui_mapper_service import UiMapperService


class MapperOnDemandService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.mapper = UiMapperService(settings)

    def list_packages(self) -> list[str]:
        output = self.mapper.adb.shell("pm list packages")
        packages = []
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                packages.append(line.split(":", 1)[1])
        return sorted(packages)

    def start_app(self, package_name: str) -> dict[str, Any]:
        self.mapper.navigation_context.prepare_fresh_app_launch(package_name)
        return {"package_name": package_name, "started": True}

    def inspect(self, package_name: str, *, session_id: int | None = None) -> dict[str, Any]:
        with session_scope() as session:
            repository = SqlAlchemyMapperRepository(session)
            mapper_session = self._ensure_session(repository, package_name, session_id=session_id)
            screen, nodes, recognized = self._persist_current_screen(repository, mapper_session.id, package_name)
            repository.update_session_metadata(mapper_session.id, {
                "current_activity": {
                    "activity_kind": "on_demand_inspect",
                    "current_screen_id": screen.id,
                    "target_screen_id": screen.id,
                    "strategy_type": None,
                    "reason": "on_demand_inspect",
                    "route_signature": None,
                },
                "last_meaningful_progress_at": utc_now().isoformat(),
            })
            MapperChurnService(session, self.settings).record_snapshot(
                mapper_session.id,
                event_type="activity",
                activity_kind="on_demand_inspect",
                current_screen_id=screen.id,
                target_screen_id=screen.id,
                metadata_json={"recognized": recognized, "navigation_kind": "on_demand"},
            )
            session.commit()
            return self._inspection_payload(repository, mapper_session.id, screen.id, package_name, nodes, recognized=recognized)

    def act(
        self,
        package_name: str,
        *,
        session_id: int | None = None,
        action_id: int | None = None,
        bounds: str | None = None,
        action_type: str = "click",
    ) -> dict[str, Any]:
        with session_scope() as session:
            repository = SqlAlchemyMapperRepository(session)
            mapper_session = self._ensure_session(repository, package_name, session_id=session_id)
            source_screen, _, _ = self._persist_current_screen(repository, mapper_session.id, package_name)
            action = None
            click_bounds = bounds
            if action_id is not None:
                action = repository.get_action(action_id)
                if action is None or action.session_id != mapper_session.id:
                    raise ValueError("Mapper action not found for this session")
                click_bounds = (action.metadata_json or {}).get("bounds")
                if click_bounds is None and action.node_id is not None:
                    node = repository.get_node(action.node_id)
                    click_bounds = None if node is None else node.bounds
            if action is None:
                inferred_action_type = "system_back" if action_type == "back" else "click"
                action_key = f"on_demand:{action_type}:{click_bounds or 'back'}"
                action = repository.find_action_by_key(mapper_session.id, source_screen.id, action_key)
                if action is None:
                    action = repository.create_action(
                        session_id=mapper_session.id,
                        screen_id=source_screen.id,
                        node_id=None,
                        action_key=action_key,
                        action_type=inferred_action_type,
                        label="On-demand action",
                        safety=MapperActionSafety.SAFE,
                        executed=False,
                        metadata_json={"bounds": click_bounds} if click_bounds else {},
                    )
            if action_type == "back" or action.action_type == "system_back":
                self.mapper.adb.press_back()
                success = True
            else:
                if not click_bounds:
                    raise ValueError("click action requires bounds or a mapped action with bounds")
                success = self.mapper.ui.click_bounds(click_bounds)
            action.executed = True
            action.success = success
            to_screen_id = None
            result_type = "failed_click"
            if success:
                nodes_after = self.mapper.ui.dump_nodes()
                if not self.mapper._left_target_app(nodes_after, package_name):
                    target_screen, _, _ = self._persist_current_screen(repository, mapper_session.id, package_name, nodes=nodes_after)
                    to_screen_id = target_screen.id
                    result_type = "clicked"
                else:
                    result_type = "left_app"
            repository.create_transition(
                session_id=mapper_session.id,
                from_screen_id=source_screen.id,
                action_id=action.id,
                to_screen_id=to_screen_id,
                result_type=result_type,
                metadata_json={"navigation_kind": "on_demand"},
            )
            repository.update_session_metadata(mapper_session.id, {
                "current_activity": {
                    "activity_kind": "on_demand_act",
                    "current_screen_id": source_screen.id,
                    "target_screen_id": to_screen_id,
                    "strategy_type": "manual_guided",
                    "reason": action_type,
                    "route_signature": action.action_key,
                },
                "last_meaningful_progress_at": utc_now().isoformat(),
            })
            churn = MapperChurnService(session, self.settings)
            churn.record_snapshot(
                mapper_session.id,
                event_type="action",
                activity_kind="on_demand_act",
                current_screen_id=source_screen.id,
                target_screen_id=to_screen_id,
                strategy_type=action.action_type,
                route_signature=action.action_key,
                metadata_json={"success": success, "result_type": result_type, "navigation_kind": "on_demand"},
            )
            if success and to_screen_id is not None:
                churn.record_snapshot(
                    mapper_session.id,
                    event_type="meaningful_progress",
                    activity_kind="on_demand_act",
                    current_screen_id=source_screen.id,
                    target_screen_id=to_screen_id,
                    strategy_type=action.action_type,
                    route_signature=action.action_key,
                    metadata_json={"navigation_kind": "on_demand"},
                )
            session.commit()
            return {
                "session_id": mapper_session.id,
                "source_screen_id": source_screen.id,
                "resulting_screen_id": to_screen_id,
                "action_id": action.id,
                "success": success,
                "result_type": result_type,
            }

    def _ensure_session(self, repository: SqlAlchemyMapperRepository, package_name: str, *, session_id: int | None) -> Any:
        if session_id is not None:
            mapper_session = repository.get_session(session_id)
            if mapper_session is None:
                raise ValueError("Mapper session not found")
            return mapper_session
        existing = repository.get_resumable_session(package_name)
        if existing is not None and (existing.metadata_json or {}).get("on_demand"):
            return existing
        mapper_session = repository.create_session(
            package_name=package_name,
            mode=MapperMode.LIGHT,
            skip_dangerous_actions=True,
            max_depth=1,
            max_actions=1000,
            max_scrolls=0,
            metadata_json={"mode": MapperMode.LIGHT.value, "on_demand": True},
        )
        mapper_session.status = MapperSessionStatus.RUNNING
        mapper_session.started_at = utc_now()
        repository.session.flush()
        return mapper_session

    def _persist_current_screen(self, repository: SqlAlchemyMapperRepository, session_id: int, package_name: str, *, nodes: list[dict[str, Any]] | None = None):
        nodes = nodes if nodes is not None else self.mapper.ui.dump_nodes()
        if self.mapper._left_target_app(nodes, package_name):
            raise ValueError(f"Current screen is not inside {package_name}")
        fingerprint = self.mapper.fingerprint_service.fingerprint(nodes, package_name)
        structural_signature = self.mapper.fingerprint_service.structural_signature(nodes, package_name)
        screen = repository.find_screen_by_fingerprint(session_id, fingerprint)
        recognized = screen is not None
        if screen is None:
            screen = repository.find_screen_by_structural_signature(session_id, structural_signature)
            if screen is not None:
                recognized = True
                repository.increment_screen_visit_count(screen.id)
                repository.record_screen_observation(screen.id, fingerprint)
            else:
                ordinal = len(repository.list_screens(session_id))
                screen = repository.create_screen(
                    session_id=session_id,
                    fingerprint=fingerprint,
                    structural_signature=structural_signature,
                    screen_key=f"screen-{ordinal + 1}",
                    depth=0,
                    ordinal=ordinal,
                    metadata_json={
                        "node_count": len(nodes),
                        "navigation_context": structural_signature,
                        "completion_state": MapperScreenCompletionState.PENDING.value,
                        "observed_fingerprints": [fingerprint],
                        "observation_count": 1,
                    },
                )
                for index, node in enumerate(nodes):
                    repository.create_node(
                        screen_id=screen.id,
                        node_key=self.mapper._node_key(node, index),
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
        candidates = self.mapper._extract_candidates(nodes, package_name)
        for candidate in candidates:
            if repository.find_action_by_key(session_id, screen.id, candidate.action_key) is None:
                safety = self.mapper.safety_service.classify(candidate.node, candidate.label)
                repository.create_action(
                    session_id=session_id,
                    screen_id=screen.id,
                    node_id=None,
                    action_key=candidate.action_key,
                    action_type="click",
                    label=candidate.label,
                    safety=safety,
                    executed=False,
                    metadata_json={"bounds": candidate.bounds},
                )
        repository.update_screen_metadata(screen.id, {"known_candidate_count": len(candidates), "accumulated_node_count": len(nodes)})
        return screen, nodes, recognized

    def _inspection_payload(self, repository: SqlAlchemyMapperRepository, session_id: int, screen_id: int, package_name: str, nodes: list[dict[str, Any]], *, recognized: bool) -> dict[str, Any]:
        screen = repository.get_screen(screen_id)
        actions = repository.list_actions(session_id, screen_id=screen_id)
        return {
            "session_id": session_id,
            "package_name": package_name,
            "screen_id": screen_id,
            "recognized": recognized,
            "screen_key": None if screen is None else screen.screen_key,
            "visible_texts": [text for text in {str(node.get("text") or node.get("content_desc") or "").strip() for node in nodes} if text],
            "candidates": [
                {
                    "action_id": action.id,
                    "action_key": action.action_key,
                    "label": action.label,
                    "action_type": action.action_type,
                    "executed": action.executed,
                    "success": action.success,
                    "bounds": (action.metadata_json or {}).get("bounds"),
                }
                for action in actions if not action.action_key.startswith("return:")
            ],
            "node_count": len(nodes),
        }
