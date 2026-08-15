from __future__ import annotations

from fastapi.testclient import TestClient

from lib.bootstrap import create_api_app

client = TestClient(create_api_app())


def test_healthcheck() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
