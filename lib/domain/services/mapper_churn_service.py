from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session

from lib.core.settings import Settings, load_settings
from lib.core.utils.clock import utc_now
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_model import MapperRuntimeSnapshot
from lib.domain.models.mapper_types import MapperChurnMode, MapperChurnSeverity, MapperScreenCompletionState
from lib.domain.services.mapper_route_planner_service import RESTART


class MapperChurnService:
    HISTORY_LIMIT = 200

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or load_settings()
        self.repository = SqlAlchemyMapperRepository(session)

    def record_snapshot(
        self,
        session_id: int,
        *,
        event_type: str,
        activity_kind: str | None = None,
        current_screen_id: int | None = None,
        target_screen_id: int | None = None,
        strategy_type: str | None = None,
        route_signature: str | None = None,
        duration_ms: float | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mapper_session = self.repository.get_session(session_id)
        if mapper_session is None:
            raise LookupError("Mapper session not found")
        session_metadata = mapper_session.metadata_json or {}
        current_activity = session_metadata.get("current_activity") or {}
        activity_kind = activity_kind if activity_kind is not None else current_activity.get("activity_kind")
        current_screen_id = current_screen_id if current_screen_id is not None else current_activity.get("current_screen_id")
        target_screen_id = target_screen_id if target_screen_id is not None else current_activity.get("target_screen_id")
        strategy_type = strategy_type if strategy_type is not None else current_activity.get("strategy_type")
        route_signature = route_signature if route_signature is not None else current_activity.get("route_signature")

        screens = self.repository.list_screens(session_id)
        actions = self.repository.list_actions(session_id)
        transitions = self.repository.list_transitions(session_id)
        state_counts = {state.value: 0 for state in MapperScreenCompletionState}
        for screen in screens:
            state_counts[self.repository.get_screen_completion_state(screen.id).value] += 1
        pending_screens = state_counts[MapperScreenCompletionState.PENDING.value] + state_counts[MapperScreenCompletionState.RESUME_NEEDED.value]
        completed_screens = state_counts[MapperScreenCompletionState.CONTENT_COMPLETE.value] + state_counts[MapperScreenCompletionState.COMPLETE.value]
        progress_percent = self._session_progress_percent(screens)

        previous = self.repository.get_latest_runtime_snapshot(session_id)
        previous_metadata = {} if previous is None else dict(previous.metadata_json or {})
        new_screens = len(screens) if previous is None else len(screens) - int(previous_metadata.get("screen_total", 0))
        new_actions = len(actions) if previous is None else len(actions) - int(previous_metadata.get("action_total", 0))
        new_transitions = len(transitions) if previous is None else len(transitions) - int(previous_metadata.get("transition_total", 0))
        pending_delta = pending_screens if previous is None else pending_screens - int(previous_metadata.get("pending_screens", 0))
        completed_delta = completed_screens if previous is None else completed_screens - int(previous_metadata.get("completed_screens", 0))
        progress_delta = progress_percent if previous is None else round(progress_percent - float(previous_metadata.get("progress_percent", 0.0)), 1)

        restart_count = 0 if previous is None else previous.restart_count
        recovery_count = 0 if previous is None else previous.recovery_count
        revisit_count = 0 if previous is None else previous.revisit_count
        planner_restart_count = 0 if previous is None else previous.planner_restart_count
        planner_direct_count = 0 if previous is None else previous.planner_direct_count
        known_return_count = 0 if previous is None else previous.known_return_count
        repeated_route_count = 0 if previous is None else previous.repeated_route_count
        repeated_context_count = 0 if previous is None else previous.repeated_context_count
        clicks_since_progress = 0 if previous is None else previous.clicks_since_last_meaningful_progress

        event_metadata = dict(metadata_json or {})
        if event_type == "action":
            clicks_since_progress += 1
        if event_type == "meaningful_progress":
            clicks_since_progress = 0
        if event_type == "revisit":
            revisit_count += 1
        if event_type == "recovery":
            recovery_count += 1
            recovery_kind = event_metadata.get("recovery_kind")
            if recovery_kind == "planner_restart":
                planner_restart_count += 1
                restart_count += 1
            elif recovery_kind == "planner_direct":
                planner_direct_count += 1
            elif recovery_kind == "known_return":
                known_return_count += 1
            elif recovery_kind in {"restart", "departure_restart"}:
                restart_count += 1
        if event_type == "navigation" and strategy_type == RESTART:
            restart_count += 1
        if previous is not None and route_signature and previous.route_signature == route_signature:
            repeated_route_count += 1
        if previous is not None and target_screen_id is not None and previous.target_screen_id == target_screen_id and event_type in {"activity", "navigation", "recovery", "revisit"}:
            repeated_context_count += 1

        last_progress_at = session_metadata.get("last_meaningful_progress_at")
        seconds_since_progress = 0 if event_type == "meaningful_progress" else self._seconds_since(last_progress_at)
        snapshot_metadata = {
            "screen_total": len(screens),
            "action_total": len(actions),
            "transition_total": len(transitions),
            "pending_screens": pending_screens,
            "completed_screens": completed_screens,
            "progress_percent": progress_percent,
            **event_metadata,
        }
        snapshot = self.repository.create_runtime_snapshot(
            session_id=session_id,
            package_name=mapper_session.package_name,
            event_type=event_type,
            activity_kind=activity_kind,
            current_screen_id=current_screen_id,
            target_screen_id=target_screen_id,
            strategy_type=strategy_type,
            route_signature=route_signature,
            duration_ms=duration_ms,
            restart_count=restart_count,
            recovery_count=recovery_count,
            revisit_count=revisit_count,
            planner_restart_count=planner_restart_count,
            planner_direct_count=planner_direct_count,
            known_return_count=known_return_count,
            repeated_route_count=repeated_route_count,
            repeated_context_count=repeated_context_count,
            seconds_since_last_meaningful_progress=seconds_since_progress,
            clicks_since_last_meaningful_progress=clicks_since_progress,
            new_screens=new_screens,
            new_actions=new_actions,
            new_transitions=new_transitions,
            pending_screens_delta=pending_delta,
            completed_screens_delta=completed_delta,
            progress_delta=progress_delta,
            metadata_json=snapshot_metadata,
        )
        if self._mode() == MapperChurnMode.ACT:
            self._apply_policy_if_needed(session_id)
        return self._snapshot_payload(snapshot)

    def list_runtime_snapshots(self, session_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
        mapper_session = self.repository.get_session(session_id)
        if mapper_session is None:
            raise LookupError("Mapper session not found")
        snapshots = reversed(self.repository.list_runtime_snapshots(session_id, limit=limit))
        return [self._snapshot_payload(item) for item in snapshots]

    def get_live_churn(self, session_id: int) -> dict[str, Any]:
        mapper_session = self.repository.get_session(session_id)
        if mapper_session is None:
            raise LookupError("Mapper session not found")
        recent = list(reversed(self.repository.list_runtime_snapshots(session_id, limit=self.settings.mapper_churn_window_size)))
        latest = recent[-1] if recent else None
        current_activity = (mapper_session.metadata_json or {}).get("current_activity") or {}
        if latest is None:
            return {
                "session_id": mapper_session.id,
                "package_name": mapper_session.package_name,
                "mode": self._mode().value,
                "severity": MapperChurnSeverity.HEALTHY.value,
                "score": 0.0,
                "confidence": 0.0,
                "window_size": self.settings.mapper_churn_window_size,
                "current_activity": current_activity,
                "metrics": {},
                "evaluators": [],
                "recommendations": [],
                "applied_policy": (mapper_session.metadata_json or {}).get("frontier_policy"),
                "latest_snapshot": None,
            }

        history = self.repository.list_runtime_snapshots_for_package(
            mapper_session.package_name,
            exclude_session_id=session_id,
            activity_kind=latest.activity_kind,
            strategy_type=latest.strategy_type,
            limit=self.HISTORY_LIMIT,
        )
        if len(history) < 10:
            history = self.repository.list_runtime_snapshots_for_package(
                mapper_session.package_name,
                exclude_session_id=session_id,
                limit=self.HISTORY_LIMIT,
            )
        history = list(reversed(history))

        metrics = self._window_metrics(recent)
        evaluators = [
            self._restart_evaluator(metrics, history, latest),
            self._revisit_evaluator(metrics, history, latest),
            self._yield_evaluator(metrics, history, latest),
            self._frontier_evaluator(metrics, history, latest),
        ]
        weights = {
            "restart_churn": 0.35,
            "revisit_stagnation": 0.25,
            "low_yield_effort": 0.25,
            "frontier_stall": 0.15,
        }
        weighted_score = sum(item["score"] * weights[item["name"]] for item in evaluators)
        weighted_confidence = sum(item["confidence"] * weights[item["name"]] for item in evaluators)
        severity = self._severity(weighted_score)
        recommendations = self._recommendations(evaluators, latest)
        report = {
            "session_id": mapper_session.id,
            "package_name": mapper_session.package_name,
            "mode": self._mode().value,
            "severity": severity.value,
            "score": round(weighted_score, 3),
            "confidence": round(weighted_confidence, 3),
            "window_size": self.settings.mapper_churn_window_size,
            "current_activity": current_activity,
            "metrics": metrics,
            "evaluators": evaluators,
            "recommendations": recommendations,
            "applied_policy": (mapper_session.metadata_json or {}).get("frontier_policy"),
            "latest_snapshot": self._snapshot_payload(latest),
        }
        return report

    def _apply_policy_if_needed(self, session_id: int) -> dict[str, Any] | None:
        report = self.get_live_churn(session_id)
        if report["mode"] != MapperChurnMode.ACT.value or not report["recommendations"]:
            return None
        top = report["recommendations"][0]
        if top["confidence"] < self.settings.mapper_churn_min_confidence:
            return None
        target_screen_id = top.get("target_screen_id")
        if target_screen_id is None:
            return None
        if top["action"] not in {"switch_target", "defer_context", "penalize_branch", "mark_branch_hot"}:
            return None
        mapper_session = self.repository.get_session(session_id)
        if mapper_session is None:
            return None
        metadata = dict(mapper_session.metadata_json or {})
        policy = dict(metadata.get("frontier_policy") or {})
        penalties = dict(policy.get("deprioritized_screens") or {})
        penalty_ms = int(max(1000, min(10000, 2500 + report["score"] * 5000 * max(self.settings.mapper_churn_aggressiveness, 0.1))))
        penalties[str(target_screen_id)] = max(int(penalties.get(str(target_screen_id), 0)), penalty_ms)
        policy.update({
            "mode": MapperChurnMode.ACT.value,
            "action": top["action"],
            "target_screen_id": target_screen_id,
            "score": report["score"],
            "confidence": top["confidence"],
            "deprioritized_screens": penalties,
            "updated_at": utc_now().isoformat(),
        })
        self.repository.update_session_metadata(session_id, {"frontier_policy": policy})
        return policy

    @staticmethod
    def _session_progress_percent(screens: list[Any]) -> float:
        if not screens:
            return 0.0
        total = 0.0
        for screen in screens:
            metadata = screen.metadata_json or {}
            completion_value = metadata.get("completion_state", MapperScreenCompletionState.PENDING.value)
            completion_state = MapperScreenCompletionState(completion_value)
            known = int(metadata.get("known_candidate_count", 0))
            attempted = int(metadata.get("attempted_candidate_count", 0))
            pending = max(known - attempted, 0)
            if completion_state in (MapperScreenCompletionState.CONTENT_COMPLETE, MapperScreenCompletionState.COMPLETE):
                total += 100.0
            elif known == 0:
                total += 0.0
            elif pending == 0 and attempted > 0:
                total += 100.0
            else:
                total += round((attempted / known) * 100, 1)
        return round(total / len(screens), 1)

    @staticmethod
    def _seconds_since(value: str | None) -> int:
        parsed = MapperChurnService._parse_datetime(value)
        if parsed is None:
            return 0
        return max(0, int((utc_now() - parsed).total_seconds()))

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    def _mode(self) -> MapperChurnMode:
        try:
            return MapperChurnMode(self.settings.mapper_churn_mode)
        except ValueError:
            return MapperChurnMode.RECOMMEND

    @staticmethod
    def _window_metrics(recent: list[MapperRuntimeSnapshot]) -> dict[str, Any]:
        pair_count = max(len(recent) - 1, 1)
        current_progress = float((recent[-1].metadata_json or {}).get("progress_percent", 0.0))
        initial_progress = float((recent[0].metadata_json or {}).get("progress_percent", 0.0))
        pending_end = int((recent[-1].metadata_json or {}).get("pending_screens", 0))
        pending_start = int((recent[0].metadata_json or {}).get("pending_screens", 0))
        return {
            "window_events": len(recent),
            "window_actions": sum(1 for item in recent if item.event_type == "action"),
            "window_recoveries": sum(1 for item in recent if item.event_type == "recovery"),
            "window_restarts": sum(1 for item in recent if item.event_type in {"navigation", "recovery"} and item.strategy_type == RESTART),
            "window_revisits": sum(1 for item in recent if item.event_type == "revisit"),
            "window_value_gain": sum(max(item.new_screens, 0) + max(item.new_actions, 0) + max(item.new_transitions, 0) for item in recent),
            "window_progress_gain": round(current_progress - initial_progress, 1),
            "window_pending_delta": pending_end - pending_start,
            "window_repeat_contexts": sum(1 for previous, current in zip(recent, recent[1:]) if current.target_screen_id is not None and current.target_screen_id == previous.target_screen_id),
            "window_repeat_routes": sum(1 for previous, current in zip(recent, recent[1:]) if current.route_signature and current.route_signature == previous.route_signature),
            "current_clicks_since_progress": recent[-1].clicks_since_last_meaningful_progress,
            "current_seconds_since_progress": recent[-1].seconds_since_last_meaningful_progress,
            "restart_rate": sum(1 for item in recent if item.event_type in {"navigation", "recovery"} and item.strategy_type == RESTART) / pair_count,
            "revisit_rate": sum(1 for item in recent if item.event_type == "revisit") / max(len(recent), 1),
            "repeat_context_rate": sum(1 for previous, current in zip(recent, recent[1:]) if current.target_screen_id is not None and current.target_screen_id == previous.target_screen_id) / pair_count,
            "repeat_route_rate": sum(1 for previous, current in zip(recent, recent[1:]) if current.route_signature and current.route_signature == previous.route_signature) / pair_count,
        }

    def _restart_evaluator(self, metrics: dict[str, Any], history: list[MapperRuntimeSnapshot], latest: MapperRuntimeSnapshot) -> dict[str, Any]:
        baseline = self._history_rate(history, lambda item: item.event_type in {"navigation", "recovery"} and item.strategy_type == RESTART, default=0.15)
        score = 0.55 * self._relative_pressure(metrics["restart_rate"], baseline, floor=0.15) + 0.45 * min(metrics["window_restarts"] / 3, 1.0)
        confidence = self._confidence(history)
        explanation = f"restart pressure {metrics['restart_rate']:.2f} vs historical {baseline:.2f}"
        if metrics["window_value_gain"] > 0:
            score *= 0.75
        return {
            "name": "restart_churn",
            "score": round(min(score, 1.0), 3),
            "confidence": confidence,
            "triggered": score >= 0.35 and metrics["window_restarts"] >= 1,
            "explanation": explanation,
            "recommendation": "prefer_direct_route" if latest.strategy_type == RESTART else "penalize_branch",
        }

    def _revisit_evaluator(self, metrics: dict[str, Any], history: list[MapperRuntimeSnapshot], latest: MapperRuntimeSnapshot) -> dict[str, Any]:
        baseline = self._history_rate(history, lambda item: item.event_type == "revisit", default=0.10)
        stagnation = 1.0 if metrics["window_progress_gain"] <= 0 and metrics["window_value_gain"] == 0 else max(0.0, 1.0 - min(metrics["window_progress_gain"] / 15, 1.0))
        score = 0.6 * self._relative_pressure(metrics["revisit_rate"], baseline, floor=0.10) + 0.4 * stagnation
        explanation = f"revisit pressure {metrics['revisit_rate']:.2f} vs historical {baseline:.2f}, progress_gain={metrics['window_progress_gain']}"
        return {
            "name": "revisit_stagnation",
            "score": round(min(score, 1.0), 3),
            "confidence": self._confidence(history),
            "triggered": score >= 0.35 and metrics["window_revisits"] >= 1,
            "explanation": explanation,
            "recommendation": "defer_context" if latest.target_screen_id is not None else "switch_target",
        }

    def _yield_evaluator(self, metrics: dict[str, Any], history: list[MapperRuntimeSnapshot], latest: MapperRuntimeSnapshot) -> dict[str, Any]:
        baseline_clicks = self._history_mean(history, lambda item: item.clicks_since_last_meaningful_progress, default=2.0)
        baseline_yield = self._history_mean(history, lambda item: max(item.new_screens, 0) + max(item.new_actions, 0) + max(item.new_transitions, 0), default=1.0)
        click_pressure = self._relative_pressure(float(metrics["current_clicks_since_progress"]), baseline_clicks, floor=2.0)
        yield_penalty = 1.0 if metrics["window_value_gain"] == 0 else max(0.0, 1.0 - min(metrics["window_value_gain"] / max(baseline_yield * 2, 1.0), 1.0))
        score = 0.6 * click_pressure + 0.4 * yield_penalty
        explanation = f"clicks_since_progress={metrics['current_clicks_since_progress']} vs historical {baseline_clicks:.1f}, value_gain={metrics['window_value_gain']}"
        return {
            "name": "low_yield_effort",
            "score": round(min(score, 1.0), 3),
            "confidence": self._confidence(history),
            "triggered": score >= 0.35 and metrics["window_actions"] >= 1,
            "explanation": explanation,
            "recommendation": "switch_target" if latest.target_screen_id is not None else "mark_branch_hot",
        }

    def _frontier_evaluator(self, metrics: dict[str, Any], history: list[MapperRuntimeSnapshot], latest: MapperRuntimeSnapshot) -> dict[str, Any]:
        baseline_repeat = self._history_mean(history, lambda item: float(item.repeated_context_count), default=0.5)
        repeat_pressure = self._relative_pressure(float(metrics["window_repeat_contexts"]), baseline_repeat, floor=0.5)
        pending_stall = 1.0 if metrics["window_pending_delta"] >= 0 and metrics["window_progress_gain"] <= 0 else 0.0
        route_repeat = min(metrics["window_repeat_routes"] / max(metrics["window_events"], 1), 1.0)
        score = 0.45 * repeat_pressure + 0.35 * pending_stall + 0.20 * route_repeat
        explanation = f"repeat_contexts={metrics['window_repeat_contexts']} pending_delta={metrics['window_pending_delta']} repeat_routes={metrics['window_repeat_routes']}"
        return {
            "name": "frontier_stall",
            "score": round(min(score, 1.0), 3),
            "confidence": self._confidence(history),
            "triggered": score >= 0.35 and latest.target_screen_id is not None,
            "explanation": explanation,
            "recommendation": "penalize_branch" if latest.target_screen_id is not None else "switch_target",
        }

    def _recommendations(self, evaluators: list[dict[str, Any]], latest: MapperRuntimeSnapshot) -> list[dict[str, Any]]:
        ranked = sorted(
            (item for item in evaluators if item["triggered"]),
            key=lambda item: (item["score"] * item["confidence"], item["score"]),
            reverse=True,
        )
        recommendations: list[dict[str, Any]] = []
        seen_actions: set[str] = set()
        for item in ranked:
            action = item["recommendation"]
            if action in seen_actions:
                continue
            seen_actions.add(action)
            recommendations.append({
                "action": action,
                "confidence": round(min(1.0, item["confidence"] * max(item["score"], 0.25)), 3),
                "target_screen_id": latest.target_screen_id,
                "current_screen_id": latest.current_screen_id,
                "strategy_type": latest.strategy_type,
                "rationale": item["explanation"],
                "automatic": self._mode() == MapperChurnMode.ACT,
            })
        return recommendations

    @staticmethod
    def _history_rate(history: list[MapperRuntimeSnapshot], predicate, *, default: float) -> float:
        if not history:
            return default
        return mean(1.0 if predicate(item) else 0.0 for item in history)

    @staticmethod
    def _history_mean(history: list[MapperRuntimeSnapshot], getter, *, default: float) -> float:
        if not history:
            return default
        values = [float(getter(item)) for item in history]
        return mean(values) if values else default

    @staticmethod
    def _relative_pressure(current: float, baseline: float, *, floor: float) -> float:
        reference = max(baseline, floor)
        if current <= reference:
            return max(0.0, current / reference * 0.25)
        return min((current - reference) / reference, 1.0)

    @staticmethod
    def _confidence(history: list[MapperRuntimeSnapshot]) -> float:
        return round(min(1.0, 0.35 + (len(history) / 40)), 3)

    @staticmethod
    def _severity(score: float) -> MapperChurnSeverity:
        if score >= 0.75:
            return MapperChurnSeverity.CRITICAL
        if score >= 0.5:
            return MapperChurnSeverity.ELEVATED
        if score >= 0.25:
            return MapperChurnSeverity.WATCH
        return MapperChurnSeverity.HEALTHY

    @staticmethod
    def _snapshot_payload(snapshot: MapperRuntimeSnapshot) -> dict[str, Any]:
        return {
            "id": snapshot.id,
            "session_id": snapshot.session_id,
            "package_name": snapshot.package_name,
            "observed_at": snapshot.observed_at,
            "event_type": snapshot.event_type,
            "activity_kind": snapshot.activity_kind,
            "current_screen_id": snapshot.current_screen_id,
            "target_screen_id": snapshot.target_screen_id,
            "strategy_type": snapshot.strategy_type,
            "route_signature": snapshot.route_signature,
            "duration_ms": snapshot.duration_ms,
            "restart_count": snapshot.restart_count,
            "recovery_count": snapshot.recovery_count,
            "revisit_count": snapshot.revisit_count,
            "planner_restart_count": snapshot.planner_restart_count,
            "planner_direct_count": snapshot.planner_direct_count,
            "known_return_count": snapshot.known_return_count,
            "repeated_route_count": snapshot.repeated_route_count,
            "repeated_context_count": snapshot.repeated_context_count,
            "seconds_since_last_meaningful_progress": snapshot.seconds_since_last_meaningful_progress,
            "clicks_since_last_meaningful_progress": snapshot.clicks_since_last_meaningful_progress,
            "new_screens": snapshot.new_screens,
            "new_actions": snapshot.new_actions,
            "new_transitions": snapshot.new_transitions,
            "pending_screens_delta": snapshot.pending_screens_delta,
            "completed_screens_delta": snapshot.completed_screens_delta,
            "progress_delta": snapshot.progress_delta,
            "metadata": snapshot.metadata_json or {},
        }
