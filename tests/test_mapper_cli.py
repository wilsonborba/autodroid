from __future__ import annotations

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode, MapperSessionStatus
from lib.presentation.cli.commands.root import app

PACKAGE_NAME = "com.cli.mapper"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_cli_sessions() -> None:
    with SessionLocal() as session:
        session.execute(text(f"DELETE FROM mapper_runtime_snapshots WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name = '{PACKAGE_NAME}') OR package_name = '{PACKAGE_NAME}'"))
        session.execute(text(f"DELETE FROM mapper_transitions WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name = '{PACKAGE_NAME}')"))
        session.execute(text(f"DELETE FROM mapper_actions WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name = '{PACKAGE_NAME}')"))
        session.execute(text(f"DELETE FROM mapper_nodes WHERE screen_id IN (SELECT id FROM mapper_screens WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name = '{PACKAGE_NAME}'))"))
        session.execute(text(f"DELETE FROM mapper_screens WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name = '{PACKAGE_NAME}')"))
        session.execute(text(f"DELETE FROM mapper_sessions WHERE package_name = '{PACKAGE_NAME}'"))
        session.commit()
    yield


def _seed_cli_session() -> int:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.create_session(
            package_name=PACKAGE_NAME,
            mode=MapperMode.LIGHT,
            skip_dangerous_actions=True,
            max_depth=1,
            max_actions=8,
            max_scrolls=0,
        )
        mapper_session.status = MapperSessionStatus.RUNNING
        screen_a = repository.create_screen(session_id=mapper_session.id, fingerprint="a", screen_key="screen-a", depth=0, ordinal=0)
        screen_b = repository.create_screen(session_id=mapper_session.id, fingerprint="b", screen_key="screen-b", depth=1, ordinal=1)
        node = repository.create_node(screen_id=screen_a.id, node_key="node-1", text="Jobs", bounds="[0,0][10,10]", clickable=True)
        action = repository.create_action(session_id=mapper_session.id, screen_id=screen_a.id, node_id=node.id, action_key="click:jobs", action_type="click", label="Jobs", safety=MapperActionSafety.SAFE, executed=True, success=True)
        repository.create_transition(session_id=mapper_session.id, from_screen_id=screen_a.id, action_id=action.id, to_screen_id=screen_b.id, result_type="clicked")
        repository.update_screen_metadata(screen_a.id, {"known_candidate_count": 1, "attempted_candidate_count": 1, "successful_candidate_count": 1, "scroll_attempts": 2, "useful_scroll_discoveries": 1})
        repository.update_session_metadata(mapper_session.id, {"current_activity": {"activity_kind": "frontier_target_selected", "current_screen_id": screen_a.id, "target_screen_id": screen_b.id, "strategy_type": "restart", "reason": "cli-test", "route_signature": "restart:1"}, "last_meaningful_progress_at": "2026-08-16T12:00:00+00:00"})
        metadata = {"screen_total": 2, "action_total": 1, "transition_total": 1, "pending_screens": 1, "completed_screens": 0, "progress_percent": 0.0}
        repository.create_runtime_snapshot(session_id=mapper_session.id, package_name=PACKAGE_NAME, event_type="activity", activity_kind="frontier_target_selected", current_screen_id=screen_a.id, target_screen_id=screen_b.id, strategy_type="restart", route_signature="restart:1", restart_count=1, recovery_count=0, revisit_count=0, planner_restart_count=0, planner_direct_count=0, known_return_count=0, repeated_route_count=0, repeated_context_count=0, seconds_since_last_meaningful_progress=60, clicks_since_last_meaningful_progress=0, new_screens=0, new_actions=0, new_transitions=0, pending_screens_delta=0, completed_screens_delta=0, progress_delta=0.0, metadata_json=metadata)
        repository.create_runtime_snapshot(session_id=mapper_session.id, package_name=PACKAGE_NAME, event_type="recovery", activity_kind="recovering", current_screen_id=screen_a.id, target_screen_id=screen_b.id, strategy_type="restart", route_signature="restart:1", restart_count=2, recovery_count=1, revisit_count=0, planner_restart_count=1, planner_direct_count=0, known_return_count=0, repeated_route_count=1, repeated_context_count=1, seconds_since_last_meaningful_progress=120, clicks_since_last_meaningful_progress=3, new_screens=0, new_actions=0, new_transitions=0, pending_screens_delta=0, completed_screens_delta=0, progress_delta=0.0, metadata_json=metadata | {"recovery_kind": "planner_restart"})
        repository.create_runtime_snapshot(session_id=mapper_session.id, package_name=PACKAGE_NAME, event_type="action", activity_kind="exploring_screen", current_screen_id=screen_a.id, target_screen_id=screen_b.id, strategy_type="click", route_signature="click:jobs", restart_count=2, recovery_count=1, revisit_count=1, planner_restart_count=1, planner_direct_count=0, known_return_count=0, repeated_route_count=1, repeated_context_count=2, seconds_since_last_meaningful_progress=180, clicks_since_last_meaningful_progress=5, new_screens=0, new_actions=0, new_transitions=0, pending_screens_delta=0, completed_screens_delta=0, progress_delta=0.0, metadata_json=metadata)
        session.commit()
        return mapper_session.id


def test_mapper_progress_command_supports_package_lookup() -> None:
    session_id = _seed_cli_session()

    result = runner.invoke(app, ["mapper", "progress", "--package", PACKAGE_NAME])

    assert result.exit_code == 0
    assert f"session #{session_id}" in result.output
    assert "recoveries total=" in result.output


def test_mapper_churn_command_renders_compact_view() -> None:
    _seed_cli_session()

    result = runner.invoke(app, ["mapper", "churn", "--package", PACKAGE_NAME])

    assert result.exit_code == 0
    assert "churn=" in result.output
    assert "->" in result.output
