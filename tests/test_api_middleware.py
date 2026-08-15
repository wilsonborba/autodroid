from __future__ import annotations

from fastapi.testclient import TestClient

from lib.bootstrap import create_api_app


def test_every_request_is_logged_generically(caplog) -> None:
    # covers every route without a matching log call in each one by hand (issue #40): a route
    # that logs nothing of its own (a plain GET) still gets a request/response pair logged
    caplog.set_level("DEBUG")
    client = TestClient(create_api_app())

    response = client.get("/health")

    assert response.status_code == 200
    messages = [record.message for record in caplog.records]
    assert any(message == "--> GET /health" for message in messages)
    assert any(message.startswith("<-- GET /health 200") for message in messages)
