from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from lib.bootstrap import create_api_app
from lib.dal.local.database import SessionLocal


@pytest.fixture(autouse=True)
def _clean_flows():
    with SessionLocal() as session:
        session.execute(text("DELETE FROM mapper_flow_step_usages"))
        session.execute(text("DELETE FROM mapper_flow_steps"))
        session.execute(text("DELETE FROM mapper_flows"))
        session.commit()
    yield


class FakeFlowExecutionService:
    def run_flow(self, flow, steps, *, skip_dangerous_actions=True):
        return {
            "flow_id": flow.id,
            "name": flow.name,
            "package_name": flow.package_name,
            "steps": [{"step_id": step.id, "action_type": step.action_type, "success": True, "skipped_reason": None} for step in steps],
        }

    def run_step(self, step, *, skip_dangerous_actions=True):
        return {"step_id": step.id, "action_type": step.action_type, "success": True, "skipped_reason": None}


def test_create_and_show_flow_endpoint() -> None:
    client = TestClient(create_api_app())

    create_response = client.post(
        "/mapper/flows",
        json={
            "name": "api_flow",
            "package_name": "com.flowapi.testapp",
            "steps": [
                {"action_type": "click", "selector": {"candidates": ["Profile"]}},
                {"action_type": "scroll_up", "selector": {}},
            ],
        },
    )
    assert create_response.status_code == 200
    flow_id = create_response.json()["id"]
    assert create_response.json()["step_count"] == 2

    show_response = client.get(f"/mapper/flows/{flow_id}")
    assert show_response.status_code == 200
    assert len(show_response.json()["steps"]) == 2
    assert show_response.json()["steps"][0]["ordinal"] == 0


def test_create_flow_without_steps_or_transitions_returns_400() -> None:
    client = TestClient(create_api_app())

    response = client.post("/mapper/flows", json={"name": "invalid", "package_name": "com.invalid.testapp"})

    assert response.status_code == 400


def test_list_flows_filters_by_package() -> None:
    client = TestClient(create_api_app())
    client.post("/mapper/flows", json={"name": "flow_x", "package_name": "com.list.testapp", "steps": [{"action_type": "back", "selector": {}}]})

    response = client.get("/mapper/flows", params={"package_name": "com.list.testapp"})

    assert response.status_code == 200
    assert any(flow["name"] == "flow_x" for flow in response.json())


def test_update_and_delete_flow_endpoints() -> None:
    client = TestClient(create_api_app())
    create_response = client.post("/mapper/flows", json={"name": "update_me", "package_name": "com.update.testapp", "steps": [{"action_type": "back", "selector": {}}]})
    flow_id = create_response.json()["id"]

    update_response = client.patch(f"/mapper/flows/{flow_id}", json={"name": "updated_name"})
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "updated_name"

    delete_response = client.delete(f"/mapper/flows/{flow_id}")
    assert delete_response.status_code == 200

    show_response = client.get(f"/mapper/flows/{flow_id}")
    assert show_response.status_code == 404


def test_add_step_endpoint_reports_step_and_ancestors() -> None:
    client = TestClient(create_api_app())
    create_response = client.post("/mapper/flows", json={"name": "step_ops", "package_name": "com.stepops.testapp", "steps": [{"action_type": "back", "selector": {}}]})
    flow_id = create_response.json()["id"]

    add_response = client.post(f"/mapper/flows/{flow_id}/steps", json={"action_type": "scroll_up", "selector": {}})
    assert add_response.status_code == 200
    body = add_response.json()
    assert body["step"]["action_type"] == "scroll_up"
    assert body["ancestors"] == []  # no source_screen_id, nothing to auto-pull
    step_id = body["step"]["id"]

    remove_response = client.delete(f"/mapper/flows/{flow_id}/steps/{step_id}")
    assert remove_response.status_code == 200

    show_response = client.get(f"/mapper/flows/{flow_id}")
    assert show_response.json()["step_count"] == 1


def test_add_step_can_reuse_an_existing_step_by_id() -> None:
    client = TestClient(create_api_app())
    flow_a = client.post("/mapper/flows", json={"name": "flow_a", "package_name": "com.reuseapi.testapp", "steps": [{"action_type": "click", "selector": {"candidates": ["Home"]}}]}).json()
    shared_step_id = flow_a["steps"][0]["id"]
    flow_b = client.post("/mapper/flows", json={"name": "flow_b", "package_name": "com.reuseapi.testapp", "steps": [{"action_type": "back", "selector": {}}]}).json()

    add_response = client.post(f"/mapper/flows/{flow_b['id']}/steps", json={"step_id": shared_step_id})

    assert add_response.status_code == 200
    assert add_response.json()["step"]["id"] == shared_step_id


def test_run_flow_endpoint(monkeypatch) -> None:
    monkeypatch.setattr("lib.presentation.api.routes.mapper_flows.get_mapper_flow_execution_service", lambda: FakeFlowExecutionService())
    client = TestClient(create_api_app())
    create_response = client.post(
        "/mapper/flows",
        json={"name": "run_me", "package_name": "com.runme.testapp", "steps": [{"action_type": "click", "selector": {"candidates": ["Profile"]}}]},
    )
    flow_id = create_response.json()["id"]

    response = client.post(f"/mapper/flows/{flow_id}/run")

    assert response.status_code == 200
    assert response.json()["steps"][0]["success"] is True


def test_run_step_endpoint(monkeypatch) -> None:
    monkeypatch.setattr("lib.presentation.api.routes.mapper_flows.get_mapper_flow_execution_service", lambda: FakeFlowExecutionService())
    client = TestClient(create_api_app())
    create_response = client.post(
        "/mapper/flows",
        json={"name": "run_step_me", "package_name": "com.runstepme.testapp", "steps": [{"action_type": "click", "selector": {"candidates": ["Profile"]}}]},
    )
    flow_id = create_response.json()["id"]

    response = client.post(f"/mapper/flows/{flow_id}/steps/0/run")
    assert response.status_code == 200
    assert response.json()["success"] is True

    missing = client.post(f"/mapper/flows/{flow_id}/steps/99/run")
    assert missing.status_code == 404
