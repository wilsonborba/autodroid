from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy.orm import Session

from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_types import MapperScreenCompletionState


class MapperProgressService:
    def __init__(self, session: Session) -> None:
        self.repository = SqlAlchemyMapperRepository(session)

    def get_session_progress(self, session_id: int) -> dict[str, Any]:
        mapper_session = self.repository.get_session(session_id)
        if mapper_session is None:
            raise LookupError("Mapper session not found")
        screens = self.repository.list_screens(session_id)
        actions = self.repository.list_actions(session_id)
        transitions = self.repository.list_transitions(session_id)
        screen_progress = self.list_screen_progress(session_id)
        state_counts = Counter(item["completion_state"] for item in screen_progress)
        percent = round(sum(item["progress_percent"] for item in screen_progress) / len(screen_progress), 1) if screen_progress else 0.0
        metadata = mapper_session.metadata_json or {}
        current_activity = self.get_current_activity(session_id)
        latest_runtime = self.repository.get_latest_runtime_snapshot(session_id)
        return {
            "session_id": mapper_session.id,
            "package_name": mapper_session.package_name,
            "mode": mapper_session.mode.value,
            "status": mapper_session.status.value,
            "started_at": mapper_session.started_at,
            "finished_at": mapper_session.finished_at,
            "created_at": mapper_session.created_at,
            "progress_percent": percent,
            "screen_counts": {
                "total": len(screens),
                "pending": state_counts.get(MapperScreenCompletionState.PENDING.value, 0),
                "content_complete": state_counts.get(MapperScreenCompletionState.CONTENT_COMPLETE.value, 0),
                "resume_needed": state_counts.get(MapperScreenCompletionState.RESUME_NEEDED.value, 0),
                "complete": state_counts.get(MapperScreenCompletionState.COMPLETE.value, 0),
            },
            "action_counts": {
                "total": len(actions),
                "executed": sum(1 for action in actions if action.executed),
                "successful": sum(1 for action in actions if action.success is True),
                "pending": sum(1 for action in actions if not action.executed),
            },
            "transition_count": len(transitions),
            "revisited_screens": sum(1 for screen in screens if screen.visit_count > 1),
            "current_activity": current_activity,
            "last_meaningful_progress_at": metadata.get("last_meaningful_progress_at"),
            "recovery_counts": {
                "total": 0 if latest_runtime is None else latest_runtime.recovery_count,
                "restart": 0 if latest_runtime is None else latest_runtime.restart_count,
                "planner_restart": 0 if latest_runtime is None else latest_runtime.planner_restart_count,
                "planner_direct": 0 if latest_runtime is None else latest_runtime.planner_direct_count,
                "known_return": 0 if latest_runtime is None else latest_runtime.known_return_count,
            },
        }

    def get_current_activity(self, session_id: int) -> dict[str, Any]:
        mapper_session = self.repository.get_session(session_id)
        if mapper_session is None:
            raise LookupError("Mapper session not found")
        return (mapper_session.metadata_json or {}).get("current_activity") or {}

    def list_screen_progress(self, session_id: int) -> list[dict[str, Any]]:
        mapper_session = self.repository.get_session(session_id)
        if mapper_session is None:
            raise LookupError("Mapper session not found")
        screens = self.repository.list_screens(session_id)
        actions = self.repository.list_actions(session_id)
        transitions = self.repository.list_transitions(session_id)
        actions_by_screen: dict[int, list[Any]] = defaultdict(list)
        transitions_by_screen: dict[int, list[Any]] = defaultdict(list)
        for action in actions:
            actions_by_screen[action.screen_id].append(action)
        for transition in transitions:
            transitions_by_screen[transition.from_screen_id].append(transition)
        current_activity = (mapper_session.metadata_json or {}).get("current_activity") or {}
        current_screen_id = current_activity.get("current_screen_id")
        target_screen_id = current_activity.get("target_screen_id")
        result: list[dict[str, Any]] = []
        for screen in screens:
            screen_actions = [action for action in actions_by_screen.get(screen.id, []) if not action.action_key.startswith("return:")]
            transitions_from = transitions_by_screen.get(screen.id, [])
            completion_state = self.repository.get_screen_completion_state(screen.id)
            attempted = sum(1 for action in screen_actions if action.executed)
            successful = sum(1 for action in screen_actions if action.success is True)
            known = len(screen_actions)
            pending = max(known - attempted, 0)
            progress = self._screen_progress_percent(completion_state, known, pending, attempted)
            metadata = screen.metadata_json or {}
            result.append({
                "screen_id": screen.id,
                "screen_key": screen.screen_key,
                "depth": screen.depth,
                "visit_count": screen.visit_count,
                "completion_state": completion_state.value,
                "is_current_screen": screen.id == current_screen_id,
                "is_current_target": screen.id == target_screen_id,
                "known_candidates": known,
                "attempted_candidates": attempted,
                "successful_candidates": successful,
                "pending_candidates": pending,
                "known_children": sum(1 for transition in transitions_from if transition.to_screen_id is not None and transition.result_type == "clicked"),
                "progress_percent": progress,
                "last_activity_at": metadata.get("last_activity_at"),
                "observation_count": metadata.get("observation_count", 1),
                "scroll_attempts": metadata.get("scroll_attempts", 0),
                "useful_scroll_discoveries": metadata.get("useful_scroll_discoveries", 0),
            })
        result.sort(key=lambda item: (item["is_current_target"] is False, item["progress_percent"], item["depth"], item["screen_id"]))
        return result

    def get_screen_progress(self, session_id: int, screen_id: int) -> dict[str, Any]:
        screens = self.list_screen_progress(session_id)
        for item in screens:
            if item["screen_id"] == screen_id:
                return item
        raise LookupError("Mapper screen not found")

    @staticmethod
    def _screen_progress_percent(completion_state: MapperScreenCompletionState, known_candidates: int, pending_candidates: int, attempted_candidates: int) -> float:
        if completion_state in (MapperScreenCompletionState.CONTENT_COMPLETE, MapperScreenCompletionState.COMPLETE):
            return 100.0
        if known_candidates == 0:
            return 0.0
        if pending_candidates == 0 and attempted_candidates > 0:
            return 100.0
        return round((attempted_candidates / known_candidates) * 100, 1)
