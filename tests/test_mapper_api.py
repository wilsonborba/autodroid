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
