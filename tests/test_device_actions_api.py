from __future__ import annotations

from fastapi.testclient import TestClient

from lib.bootstrap import create_api_app


class FakeExecutionService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def execute_on_demand(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "step_id": 42,
            "action_type": kwargs.get("action_type") or "click",
            "success": True,
            "skipped_reason": None,
            "resulting_screen_id": 7,
        }


class FailingExecutionService:
    def execute_on_demand(self, **kwargs):
        raise ValueError("Provide either target_action_id or action_type")


def test_execute_action_endpoint_calls_execute_on_demand(monkeypatch) -> None:
    fake = FakeExecutionService()
    monkeypatch.setattr("lib.presentation.api.routes.device_actions.get_mapper_flow_execution_service", lambda: fake)
    client = TestClient(create_api_app())

    response = client.post(
        "/device/actions",
        json={"package_name": "com.device.testapp", "target_action_id": 123, "current_screen_id": 5},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["resulting_screen_id"] == 7
    assert fake.calls == [{
        "package_name": "com.device.testapp", "target_action_id": 123, "target_screen_id": None,
        "current_screen_id": 5, "action_type": None, "selector": None, "params": None,
    }]


def test_execute_action_endpoint_returns_400_on_invalid_request(monkeypatch) -> None:
    monkeypatch.setattr("lib.presentation.api.routes.device_actions.get_mapper_flow_execution_service", lambda: FailingExecutionService())
    client = TestClient(create_api_app())

    response = client.post("/device/actions", json={"package_name": "com.device.testapp"})

    assert response.status_code == 400
