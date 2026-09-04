from __future__ import annotations

from fastapi.testclient import TestClient

from lib.bootstrap import create_api_app


def test_create_and_get_job_round_trips_payload_json() -> None:
    # issue #46: payload_json wasn't exposed on JobResponse at all, so a client had no way to
    # read back e.g. a mapper.remap job's package_name to correlate it to its mapper session
    # for live progress
    client = TestClient(create_api_app())

    created = client.post("/jobs", json={
        "job_type": "mapper.remap",
        "adapter_name": "mapper",
        "payload": {"package_name": "com.linkedin.android", "strategy": "complement", "mode": "deep"},
    })
    assert created.status_code == 200, created.text
    job_id = created.json()["id"]
    assert created.json()["payload_json"] == {"package_name": "com.linkedin.android", "strategy": "complement", "mode": "deep"}

    fetched = client.get(f"/jobs/{job_id}")
    assert fetched.status_code == 200
    assert fetched.json()["payload_json"] == {"package_name": "com.linkedin.android", "strategy": "complement", "mode": "deep"}


def test_get_job_returns_404_for_an_unknown_id() -> None:
    client = TestClient(create_api_app())

    response = client.get("/jobs/999999")

    assert response.status_code == 404
