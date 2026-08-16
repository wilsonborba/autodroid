from __future__ import annotations

from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from lib.bootstrap import create_api_app
from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_flow_repository import SqlAlchemyMapperFlowRepository
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_types import MapperActionSafety, MapperFlowFailureType, MapperMode, MapperSessionStatus


class FakeMapperEngine:
    def run(self, config):
        return {
            "session_id": 99,
            "package_name": config.package_name,
            "mode": config.mode.value,
            "screens_recorded": 1,
            "actions_executed": 0,
            "scrolls_used": 0,
            "revisited_screens": 0,
            "status": "completed",
        }

    def remap_screen(self, session_id: int, screen_id: int):
        return {
            "session_id": session_id,
            "screen_id": screen_id,
            "package_name": "com.linkedin.android",
            "mode": "light",
            "screens_recorded": 0,
            "actions_executed": 1,
            "scrolls_used": 0,
            "revisited_screens": 1,
            "status": "completed",
        }


def test_mapper_run_endpoint(monkeypatch) -> None:
    monkeypatch.setattr('lib.presentation.api.routes.mapper.get_mapper_engine', lambda: FakeMapperEngine())
    client = TestClient(create_api_app())

    response = client.post('/mapper/run', json={"package_name": "com.linkedin.android", "mode": "light", "skip_dangerous_actions": True})

    assert response.status_code == 200
    assert response.json()["session_id"] == 99
    assert response.json()["reused"] is False


class CapturingMapperEngine:
    def __init__(self) -> None:
        self.received_config = None

    def run(self, config):
        self.received_config = config
        return {
            "session_id": 1,
            "package_name": config.package_name,
            "mode": config.mode.value,
            "screens_recorded": 0,
            "actions_executed": 0,
            "scrolls_used": 0,
            "revisited_screens": 0,
            "status": "completed",
            "reused": True,
        }


def test_mapper_run_endpoint_forwards_override_flag(monkeypatch) -> None:
    engine = CapturingMapperEngine()
    monkeypatch.setattr('lib.presentation.api.routes.mapper.get_mapper_engine', lambda: engine)
    client = TestClient(create_api_app())

    response = client.post('/mapper/run', json={"package_name": "com.linkedin.android", "mode": "light", "override": True})

    assert response.status_code == 200
    assert response.json()["reused"] is True
    assert engine.received_config.override is True


class FakeMapperExportService:
    def export_session(self, session_id: int, output_dir):
        return output_dir / f"mapper_session_{session_id}"


def test_mapper_export_endpoint(monkeypatch) -> None:
    monkeypatch.setattr('lib.presentation.api.routes.mapper.get_mapper_export_service', lambda: FakeMapperExportService())
    client = TestClient(create_api_app())

    response = client.post('/mapper/sessions/42/export')

    assert response.status_code == 200
    assert response.json()['session_id'] == 42


def _seed_graph() -> dict:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.create_session(
            package_name="com.api.testapp",
            mode=MapperMode.LIGHT,
            skip_dangerous_actions=True,
            max_depth=1,
            max_actions=8,
            max_scrolls=0,
        )
        mapper_session.status = MapperSessionStatus.COMPLETED
        screen_a = repository.create_screen(session_id=mapper_session.id, fingerprint="a", screen_key="screen-a", depth=0, ordinal=0)
        screen_b = repository.create_screen(session_id=mapper_session.id, fingerprint="b", screen_key="screen-b", depth=1, ordinal=1)
        node = repository.create_node(screen_id=screen_a.id, node_key="node-1", text="Profile", clickable=True)
        action = repository.create_action(
            session_id=mapper_session.id,
            screen_id=screen_a.id,
            node_id=node.id,
            action_key="click:profile",
            action_type="click",
            label="Profile",
            safety=MapperActionSafety.SAFE,
        )
        transition = repository.create_transition(session_id=mapper_session.id, from_screen_id=screen_a.id, action_id=action.id, to_screen_id=screen_b.id, result_type="clicked")
        session.commit()
        return {"session_id": mapper_session.id, "screen_a_id": screen_a.id, "screen_b_id": screen_b.id, "action_id": action.id, "transition_id": transition.id}


def test_list_and_show_mapper_screens_endpoint() -> None:
    ids = _seed_graph()
    client = TestClient(create_api_app())

    list_response = client.get(f"/mapper/sessions/{ids['session_id']}/screens")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 2

    detail_response = client.get(f"/mapper/sessions/{ids['session_id']}/screens/{ids['screen_a_id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()['nodes'][0]['text'] == 'Profile'


def test_list_mapper_actions_endpoint_with_filters() -> None:
    ids = _seed_graph()
    client = TestClient(create_api_app())

    response = client.get(f"/mapper/sessions/{ids['session_id']}/actions", params={"safety": "safe"})
    assert response.status_code == 200
    assert len(response.json()) == 1

    invalid = client.get(f"/mapper/sessions/{ids['session_id']}/actions", params={"safety": "not-a-safety"})
    assert invalid.status_code == 400


def test_list_mapper_transitions_endpoint() -> None:
    ids = _seed_graph()
    client = TestClient(create_api_app())

    response = client.get(f"/mapper/sessions/{ids['session_id']}/transitions")
    assert response.status_code == 200
    assert response.json()[0]['result_type'] == 'clicked'


def test_mapper_on_demand_endpoints(monkeypatch) -> None:
    monkeypatch.setattr("lib.presentation.api.routes.mapper.get_mapper_on_demand_service", lambda: FakeOnDemandMapperService())
    client = TestClient(create_api_app())

    packages = client.get("/mapper/apps")
    assert packages.status_code == 200
    assert "com.linkedin.android" in packages.json()

    started = client.post("/mapper/apps/com.linkedin.android/start")
    assert started.status_code == 200
    assert started.json()["started"] is True

    inspected = client.get("/mapper/on-demand/inspect", params={"package_name": "com.linkedin.android"})
    assert inspected.status_code == 200
    assert inspected.json()["screen_id"] == 7

    acted = client.post("/mapper/on-demand/actions", json={"package_name": "com.linkedin.android", "session_id": 77, "action_id": 1})
    assert acted.status_code == 200
    assert acted.json()["resulting_screen_id"] == 8


def test_mapper_progress_endpoints() -> None:
    ids = _seed_graph()
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        repository.update_session_metadata(ids["session_id"], {"current_activity": {"activity_kind": "exploring_screen", "current_screen_id": ids["screen_a_id"], "target_screen_id": ids["screen_b_id"], "strategy_type": "direct_path", "reason": "test", "route_signature": "direct:1"}, "last_meaningful_progress_at": "2026-08-16T12:00:00+00:00"})
        repository.update_screen_metadata(ids["screen_a_id"], {"known_candidate_count": 1, "attempted_candidate_count": 1, "successful_candidate_count": 1})
        session.commit()
    client = TestClient(create_api_app())

    session_progress = client.get(f"/mapper/sessions/{ids['session_id']}/progress")
    assert session_progress.status_code == 200
    assert session_progress.json()["current_activity"]["activity_kind"] == "exploring_screen"

    screens_progress = client.get(f"/mapper/sessions/{ids['session_id']}/progress/screens")
    assert screens_progress.status_code == 200
    assert len(screens_progress.json()) == 2

    screen_progress = client.get(f"/mapper/sessions/{ids['session_id']}/progress/screens/{ids['screen_a_id']}")
    assert screen_progress.status_code == 200
    assert screen_progress.json()["known_candidates"] == 1

    activity = client.get(f"/mapper/sessions/{ids['session_id']}/progress/activity")
    assert activity.status_code == 200
    assert activity.json()["route_signature"] == "direct:1"


def test_mapper_churn_endpoints() -> None:
    ids = _seed_graph()
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_session(ids["session_id"])
        repository.update_session_metadata(ids["session_id"], {"current_activity": {"activity_kind": "frontier_target_selected", "current_screen_id": ids["screen_a_id"], "target_screen_id": ids["screen_b_id"], "strategy_type": "restart", "reason": "test", "route_signature": "restart:1"}, "last_meaningful_progress_at": "2026-08-16T12:00:00+00:00"})
        snapshot_metadata = {"screen_total": 2, "action_total": 1, "transition_total": 1, "pending_screens": 1, "completed_screens": 0, "progress_percent": 0.0}
        repository.create_runtime_snapshot(session_id=ids["session_id"], package_name=mapper_session.package_name, event_type="activity", activity_kind="frontier_target_selected", current_screen_id=ids["screen_a_id"], target_screen_id=ids["screen_b_id"], strategy_type="restart", route_signature="restart:1", restart_count=1, recovery_count=0, revisit_count=0, planner_restart_count=0, planner_direct_count=0, known_return_count=0, repeated_route_count=0, repeated_context_count=0, seconds_since_last_meaningful_progress=60, clicks_since_last_meaningful_progress=0, new_screens=0, new_actions=0, new_transitions=0, pending_screens_delta=0, completed_screens_delta=0, progress_delta=0.0, metadata_json=snapshot_metadata)
        repository.create_runtime_snapshot(session_id=ids["session_id"], package_name=mapper_session.package_name, event_type="recovery", activity_kind="recovering", current_screen_id=ids["screen_a_id"], target_screen_id=ids["screen_b_id"], strategy_type="restart", route_signature="restart:1", restart_count=2, recovery_count=1, revisit_count=0, planner_restart_count=1, planner_direct_count=0, known_return_count=0, repeated_route_count=1, repeated_context_count=1, seconds_since_last_meaningful_progress=120, clicks_since_last_meaningful_progress=2, new_screens=0, new_actions=0, new_transitions=0, pending_screens_delta=0, completed_screens_delta=0, progress_delta=0.0, metadata_json=snapshot_metadata | {"recovery_kind": "planner_restart"})
        repository.create_runtime_snapshot(session_id=ids["session_id"], package_name=mapper_session.package_name, event_type="action", activity_kind="exploring_screen", current_screen_id=ids["screen_a_id"], target_screen_id=ids["screen_b_id"], strategy_type="click", route_signature="click:profile", restart_count=2, recovery_count=1, revisit_count=1, planner_restart_count=1, planner_direct_count=0, known_return_count=0, repeated_route_count=1, repeated_context_count=2, seconds_since_last_meaningful_progress=180, clicks_since_last_meaningful_progress=5, new_screens=0, new_actions=0, new_transitions=0, pending_screens_delta=0, completed_screens_delta=0, progress_delta=0.0, metadata_json=snapshot_metadata)
        session.commit()

    client = TestClient(create_api_app())

    churn = client.get(f"/mapper/sessions/{ids['session_id']}/churn")
    assert churn.status_code == 200
    assert churn.json()["severity"] in {"watch", "elevated", "critical"}
    assert len(churn.json()["recommendations"]) >= 1

    telemetry = client.get(f"/mapper/sessions/{ids['session_id']}/churn/telemetry")
    assert telemetry.status_code == 200
    assert len(telemetry.json()) == 3


def test_mapper_graph_endpoint() -> None:
    ids = _seed_graph()
    client = TestClient(create_api_app())

    response = client.get(f"/mapper/sessions/{ids['session_id']}/graph")
    assert response.status_code == 200
    body = response.json()
    assert body['package_name'] == 'com.api.testapp'
    assert len(body['screens']) == 2
    assert len(body['transitions']) == 1


def test_latest_mapper_session_endpoint() -> None:
    ids = _seed_graph()
    client = TestClient(create_api_app())

    response = client.get("/mapper/apps/com.api.testapp/latest-session")
    assert response.status_code == 200
    assert response.json()['id'] == ids['session_id']

    missing = client.get("/mapper/apps/com.unknown.testapp/latest-session")
    assert missing.status_code == 404


def _fake_settings(*, enabled: bool, threshold: int = 3) -> SimpleNamespace:
    return SimpleNamespace(mapper_auto_remap_enabled=enabled, mapper_auto_remap_threshold=threshold, timezone=ZoneInfo("UTC"))


def test_remap_candidates_endpoint_returns_empty_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr("lib.presentation.api.routes.mapper.get_settings", lambda: _fake_settings(enabled=False))
    client = TestClient(create_api_app())

    response = client.get("/mapper/apps/remap-candidates")

    assert response.status_code == 200
    assert response.json() == []


def test_remap_candidates_endpoint_returns_candidates_when_enabled(monkeypatch) -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        for _ in range(3):
            repository.record_failure(package_name="com.apicandidate.testapp", failure_type=MapperFlowFailureType.CLICK_FAILED)
        session.commit()

    monkeypatch.setattr("lib.presentation.api.routes.mapper.get_settings", lambda: _fake_settings(enabled=True))
    client = TestClient(create_api_app())

    response = client.get("/mapper/apps/remap-candidates")

    assert response.status_code == 200
    names = [candidate["package_name"] for candidate in response.json()]
    assert "com.apicandidate.testapp" in names


def test_remap_apps_endpoint_queues_jobs_for_selected_packages() -> None:
    client = TestClient(create_api_app())

    response = client.post("/mapper/apps/remap", json={"package_names": ["com.remap1.testapp", "com.remap2.testapp"], "strategy": "override"})

    assert response.status_code == 200
    queued = response.json()["queued"]
    assert len(queued) == 2
    assert {item["package_name"] for item in queued} == {"com.remap1.testapp", "com.remap2.testapp"}


def test_remap_apps_endpoint_requires_a_selection() -> None:
    client = TestClient(create_api_app())

    response = client.post("/mapper/apps/remap", json={})

    assert response.status_code == 400


def test_mapper_screen_remap_endpoint(monkeypatch) -> None:
    monkeypatch.setattr('lib.presentation.api.routes.mapper.get_mapper_engine', lambda: FakeMapperEngine())
    client = TestClient(create_api_app())

    response = client.post('/mapper/sessions/42/screens/7/remap')

    assert response.status_code == 200
    assert response.json()['session_id'] == 42
    assert response.json()['screen_id'] == 7
    assert response.json()['actions_executed'] == 1


def test_mapper_screen_remap_endpoint_returns_404(monkeypatch) -> None:
    class MissingMapperEngine(FakeMapperEngine):
        def remap_screen(self, session_id: int, screen_id: int):
            raise LookupError(f"Mapper screen {screen_id} not found")

    monkeypatch.setattr('lib.presentation.api.routes.mapper.get_mapper_engine', lambda: MissingMapperEngine())
    client = TestClient(create_api_app())

    response = client.post('/mapper/sessions/42/screens/7/remap')

    assert response.status_code == 404


def test_mapper_screen_remap_endpoint_returns_400(monkeypatch) -> None:
    class InvalidMapperEngine(FakeMapperEngine):
        def remap_screen(self, session_id: int, screen_id: int):
            raise ValueError(f"Mapper screen {screen_id} does not belong to session {session_id}")

    monkeypatch.setattr('lib.presentation.api.routes.mapper.get_mapper_engine', lambda: InvalidMapperEngine())
    client = TestClient(create_api_app())

    response = client.post('/mapper/sessions/42/screens/7/remap')

    assert response.status_code == 400


class FakeOnDemandMapperService:
    def list_packages(self):
        return ["com.linkedin.android", "com.example.testapp"]

    def start_app(self, package_name: str):
        return {"package_name": package_name, "started": True}

    def inspect(self, package_name: str, *, session_id: int | None = None):
        return {
            "session_id": session_id or 77,
            "package_name": package_name,
            "screen_id": 7,
            "recognized": True,
            "screen_key": "screen-7",
            "visible_texts": ["Profile", "Jobs"],
            "candidates": [{"action_id": 1, "action_key": "click:1:jobs", "label": "Jobs", "action_type": "click", "executed": False, "success": None, "bounds": "[1,1][2,2]"}],
            "node_count": 12,
        }

    def act(self, package_name: str, *, session_id: int | None = None, action_id: int | None = None, bounds: str | None = None, action_type: str = "click"):
        return {
            "session_id": session_id or 77,
            "source_screen_id": 7,
            "resulting_screen_id": 8,
            "action_id": action_id or 1,
            "success": True,
            "result_type": "clicked",
        }
