"""Abuse limits for the public deployment, through the real ASGI stack."""

import itertools

import pytest
from fastapi.testclient import TestClient

from server import config
from server.db import init_db
from server.main import app

_ips = itertools.count(1)


@pytest.fixture()
def client():
    init_db()
    return TestClient(app)


def _ip():
    # A fresh client per test so fixed windows never bleed between tests.
    return {"X-Forwarded-For": f"10.0.0.{next(_ips)}"}


def test_login_is_throttled(client):
    h = _ip()
    codes = [client.post("/login", data={"username": "x", "password": "y"}, headers=h, follow_redirects=False).status_code
             for _ in range(config.RATE_LIMIT_LOGIN_PER_MIN + 1)]
    assert codes[-1] == 429 and 429 not in codes[:-1]
    r = client.post("/login", data={"username": "x", "password": "y"}, headers=h, follow_redirects=False)
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_reads_are_never_limited(client):
    h = _ip()
    assert all(client.get("/api/demo-clock", headers=h).status_code == 200 for _ in range(config.RATE_LIMIT_WRITES_PER_MIN + 5))


def test_writes_are_limited_per_client(client, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_WRITES_PER_MIN", 3)
    h = _ip()
    codes = [client.post("/api/offer", json={}, headers=h).status_code for _ in range(4)]
    assert codes[-1] == 429 and 429 not in codes[:-1]
    assert client.post("/api/offer", json={}, headers=_ip()).status_code != 429  # another client is unaffected


def test_clock_advance_is_bounded(client):
    h = _ip()
    assert client.post("/api/demo-clock/advance", json={"amount": 100000, "unit": "day"}, headers=h).status_code == 400
    assert client.post("/api/demo-clock/advance", json={"amount": 0, "unit": "day"}, headers=h).status_code == 400
    assert client.post("/api/demo-clock/advance", json={"amount": -5, "unit": "hour"}, headers=h).status_code == 400


def test_customer_creation_has_a_global_cap(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_DEBTS", 0)
    r = client.post("/api/debts", json={"name": "Cap", "phone": "+15555550123", "amount_due": 10}, headers=_ip())
    assert r.status_code == 409


def test_vapi_webhooks_refuse_without_the_secret(client, monkeypatch):
    payload = {"message": {"type": "tool-calls", "toolCalls": []}}
    monkeypatch.setattr(config, "VAPI_WEBHOOK_SECRET", "")
    assert client.post("/api/vapi/tools", json=payload, headers=_ip()).status_code == 403
    monkeypatch.setattr(config, "VAPI_WEBHOOK_SECRET", "s3cret")
    assert client.post("/api/vapi/tools", json=payload, headers={**_ip(), "x-vapi-secret": "wrong"}).status_code == 403
    assert client.post("/api/vapi/events", json=payload, headers=_ip()).status_code == 403
    ok = client.post("/api/vapi/tools", json=payload, headers={**_ip(), "x-vapi-secret": "s3cret"})
    assert ok.status_code == 200
