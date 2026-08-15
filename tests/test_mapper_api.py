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
