from __future__ import annotations

from fastapi.testclient import TestClient

from lib.bootstrap import create_api_app


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
