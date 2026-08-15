from __future__ import annotations

from fastapi.testclient import TestClient

from lib.bootstrap import create_api_app


def test_openapi_schema_documents_every_route_group() -> None:
    client = TestClient(create_api_app())

    response = client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    tag_names = {tag["name"] for tag in spec.get("tags", [])}
    assert {"mapper", "mapper-flows", "device-actions", "jobs"} <= tag_names
    # every documented tag has a real description, not just a bare name (issue #32 follow-up:
    # an agent reading the docs needs to understand each group without reading the repo)
    for tag in spec["tags"]:
        assert tag.get("description")


def test_docs_endpoint_serves_scalar() -> None:
    client = TestClient(create_api_app())

    response = client.get("/docs")

    assert response.status_code == 200
    assert "@scalar/api-reference" in response.text
