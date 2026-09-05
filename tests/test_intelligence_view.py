"""The Intelligence page loads from one endpoint, and the edge may cache it."""

from fastapi.testclient import TestClient

from server.db import init_db
from server.intelligence.schema import init_intel_db
from server.main import app


def test_view_returns_status_and_a_cache_header():
    init_db()
    init_intel_db()
    r = TestClient(app).get("/api/intelligence/view", headers={"X-Forwarded-For": "10.9.9.1"})
    assert r.status_code == 200
    assert "s-maxage" in r.headers.get("cache-control", "")
    body = r.json()
    assert "status" in body and "available" in body["status"]
    # On an empty intelligence DB the page gets only the status; when built,
    # every panel's payload rides along.
    if body["status"]["available"]:
        assert {"portfolio", "network", "statistics", "scenarios"} <= set(body)
