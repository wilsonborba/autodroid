from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import text

from lib.core.settings import load_settings
from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_types import MapperMode, MapperSessionStatus
from lib.domain.services.mapper_churn_service import MapperChurnService

_TEST_PACKAGES = (
    "com.churn.telemetry",
    "com.churn.high",
    "com.churn.low",
    "com.churn.productive",
    "com.churn.act",
)


@pytest.fixture(autouse=True)
def _clean_churn_sessions() -> None:
    names = ",".join(f"'{name}'" for name in _TEST_PACKAGES)
    with SessionLocal() as session:
        session.execute(text(f"DELETE FROM mapper_runtime_snapshots WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name IN ({names})) OR package_name IN ({names})"))
        session.execute(text(f"DELETE FROM mapper_transitions WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name IN ({names}))"))
        session.execute(text(f"DELETE FROM mapper_actions WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name IN ({names}))"))
        session.execute(text(f"DELETE FROM mapper_nodes WHERE screen_id IN (SELECT id FROM mapper_screens WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name IN ({names})))"))
        session.execute(text(f"DELETE FROM mapper_screens WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name IN ({names}))"))
        session.execute(text(f"DELETE FROM mapper_sessions WHERE package_name IN ({names})"))
        session.commit()
    yield
    with SessionLocal() as session:
        session.execute(text(f"DELETE FROM mapper_runtime_snapshots WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name IN ({names})) OR package_name IN ({names})"))
        session.execute(text(f"DELETE FROM mapper_transitions WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name IN ({names}))"))
        session.execute(text(f"DELETE FROM mapper_actions WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name IN ({names}))"))
        session.execute(text(f"DELETE FROM mapper_nodes WHERE screen_id IN (SELECT id FROM mapper_screens WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name IN ({names})))"))
        session.execute(text(f"DELETE FROM mapper_screens WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name IN ({names}))"))
        session.execute(text(f"DELETE FROM mapper_sessions WHERE package_name IN ({names})"))
        session.commit()


def _create_session(package_name: str, *, target_screen_id: int = 2) -> int:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.create_session(
            package_name=package_name,
            mode=MapperMode.DEEP,
            skip_dangerous_actions=True,
            max_depth=4,
            max_actions=50,
            max_scrolls=5,
        )
        mapper_session.status = MapperSessionStatus.RUNNING
        repository.update_session_metadata(
            mapper_session.id,
            {
                "current_activity": {
                    "activity_kind": "frontier_target_selected",
                    "current_screen_id": 1,
                    "target_screen_id": target_screen_id,
                    "strategy_type": "restart",
                    "reason": "test",
                    "route_signature": f"restart:{target_screen_id}",
                },
                "last_meaningful_progress_at": "2026-08-16T12:00:00+00:00",
            },
        )
        session.commit()
        return mapper_session.id


def _snapshot_defaults() -> dict:
    return {
        "activity_kind": "frontier_target_selected",
        "current_screen_id": 1,
        "target_screen_id": 2,
        "strategy_type": "restart",
        "route_signature": "restart:2",
        "restart_count": 0,
        "recovery_count": 0,
        "revisit_count": 0,
        "planner_restart_count": 0,
        "planner_direct_count": 0,
        "known_return_count": 0,
        "repeated_route_count": 0,
        "repeated_context_count": 0,
        "seconds_since_last_meaningful_progress": 60,
        "clicks_since_last_meaningful_progress": 0,
        "new_screens": 0,
        "new_actions": 0,
        "new_transitions": 0,
        "pending_screens_delta": 0,
        "completed_screens_delta": 0,
        "progress_delta": 0.0,
        "metadata_json": {
            "screen_total": 2,
            "action_total": 1,
            "transition_total": 1,
            "pending_screens": 1,
            "completed_screens": 0,
            "progress_percent": 0.0,
        },
    }


def _create_snapshot(session_id: int, package_name: str, event_type: str, **overrides) -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        payload = _snapshot_defaults() | overrides
        repository.create_runtime_snapshot(
            session_id=session_id,
            package_name=package_name,
            event_type=event_type,
            **payload,
        )
        session.commit()


def _seed_churny_window(session_id: int, package_name: str) -> None:
    _create_snapshot(session_id, package_name, "activity")
    _create_snapshot(session_id, package_name, "recovery", restart_count=1, recovery_count=1, planner_restart_count=1, repeated_route_count=1, repeated_context_count=1, seconds_since_last_meaningful_progress=120, clicks_since_last_meaningful_progress=2, metadata_json=_snapshot_defaults()["metadata_json"] | {"recovery_kind": "planner_restart"})
    _create_snapshot(session_id, package_name, "action", strategy_type="click", route_signature="click:1", restart_count=1, recovery_count=1, revisit_count=1, repeated_route_count=1, repeated_context_count=2, seconds_since_last_meaningful_progress=180, clicks_since_last_meaningful_progress=5)
    _create_snapshot(session_id, package_name, "recovery", restart_count=2, recovery_count=2, planner_restart_count=2, repeated_route_count=2, repeated_context_count=3, seconds_since_last_meaningful_progress=240, clicks_since_last_meaningful_progress=5, metadata_json=_snapshot_defaults()["metadata_json"] | {"recovery_kind": "planner_restart"})


def test_record_snapshot_persists_runtime_telemetry() -> None:
    session_id = _create_session("com.churn.telemetry")
    with SessionLocal() as session:
        service = MapperChurnService(session, load_settings())
        payload = service.record_snapshot(session_id, event_type="activity", activity_kind="starting")
        session.commit()

    assert payload["event_type"] == "activity"
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        snapshots = repository.list_runtime_snapshots(session_id)
        matching = [item for item in snapshots if item.package_name == "com.churn.telemetry"]
        assert len(matching) == 1
        assert matching[0].activity_kind == "starting"


def test_historical_baseline_changes_churn_score() -> None:
    history_session_id = _create_session("com.churn.high")
    _seed_churny_window(history_session_id, "com.churn.high")

    current_high_session_id = _create_session("com.churn.high")
    _seed_churny_window(current_high_session_id, "com.churn.high")

    current_low_session_id = _create_session("com.churn.low")
    _seed_churny_window(current_low_session_id, "com.churn.low")

    with SessionLocal() as session:
        service = MapperChurnService(session, load_settings())
        high = service.get_live_churn(current_high_session_id)
        low = service.get_live_churn(current_low_session_id)

    assert high["score"] < low["score"]


def test_live_churn_generates_recommendations_for_low_value_loops() -> None:
    session_id = _create_session("com.churn.low")
    _seed_churny_window(session_id, "com.churn.low")

    with SessionLocal() as session:
        report = MapperChurnService(session, load_settings()).get_live_churn(session_id)

    assert report["severity"] in {"watch", "elevated", "critical"}
    assert len(report["recommendations"]) >= 1
    assert report["recommendations"][0]["action"] in {"switch_target", "defer_context", "penalize_branch", "prefer_direct_route"}


def test_productive_exploration_does_not_trigger_high_churn() -> None:
    session_id = _create_session("com.churn.productive")
    productive_metadata = _snapshot_defaults()["metadata_json"] | {"progress_percent": 35.0, "completed_screens": 1}
    _create_snapshot(session_id, "com.churn.productive", "activity", metadata_json=productive_metadata)
    _create_snapshot(session_id, "com.churn.productive", "action", strategy_type="click", route_signature="click:profile", new_screens=1, new_actions=1, new_transitions=1, completed_screens_delta=1, progress_delta=20.0, clicks_since_last_meaningful_progress=1, metadata_json=productive_metadata)
    _create_snapshot(session_id, "com.churn.productive", "meaningful_progress", strategy_type="click", route_signature="click:profile", new_screens=1, new_actions=1, new_transitions=1, completed_screens_delta=1, progress_delta=20.0, clicks_since_last_meaningful_progress=0, metadata_json=productive_metadata)

    with SessionLocal() as session:
        report = MapperChurnService(session, load_settings()).get_live_churn(session_id)

    assert report["score"] < 0.5
    assert report["severity"] in {"healthy", "watch"}


def test_act_mode_applies_bounded_frontier_policy() -> None:
    session_id = _create_session("com.churn.act", target_screen_id=9)
    _seed_churny_window(session_id, "com.churn.act")

    with SessionLocal() as session:
        settings = replace(load_settings(), mapper_churn_mode="act", mapper_churn_min_confidence=0.2, mapper_churn_aggressiveness=0.5)
        service = MapperChurnService(session, settings)
        service.record_snapshot(
            session_id,
            event_type="activity",
            activity_kind="frontier_target_selected",
            current_screen_id=1,
            target_screen_id=9,
            strategy_type="restart",
            route_signature="restart:9",
        )
        session.commit()

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_session(session_id)
        policy = (mapper_session.metadata_json or {}).get("frontier_policy") or {}
        assert policy["target_screen_id"] == 9
        assert int(policy["deprioritized_screens"]["9"]) > 0
