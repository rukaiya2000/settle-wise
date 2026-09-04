"""server/sms_client.py against a fake requests.post - no network, no texts."""

import pytest
import requests

from server import config, sms_client


@pytest.fixture()
def creds(monkeypatch):
    monkeypatch.setattr(config, "TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setattr(config, "TWILIO_FROM_NUMBER", "+15550009999")


class _Resp:
    def __init__(self, status: int, payload: dict):
        self.status_code, self._payload = status, payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        return self._payload

    @property
    def text(self):
        return str(self._payload)


def test_refuses_loudly_when_unconfigured(monkeypatch):
    for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"):
        monkeypatch.setattr(config, k, "")
    calls = []
    monkeypatch.setattr(sms_client.requests, "post", lambda *a, **kw: calls.append(1))
    with pytest.raises(sms_client.SmsNotConfigured) as e:
        sms_client.send_sms("+15550000001", "hi")
    assert "TWILIO_ACCOUNT_SID" in str(e.value)
    assert calls == []  # never touched the network


def test_posts_the_twilio_message_shape(creds, monkeypatch):
    seen = {}

    def fake_post(url, auth, data, timeout):
        seen.update(url=url, auth=auth, data=data)
        return _Resp(201, {"sid": "SM123", "status": "queued"})

    monkeypatch.setattr(sms_client.requests, "post", fake_post)
    out = sms_client.send_sms("+15550000001", "Your link")

    assert seen["url"] == "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages.json"
    assert seen["auth"] == ("ACtest", "tok")
    assert seen["data"] == {"To": "+15550000001", "From": "+15550009999", "Body": "Your link"}
    assert out == {"provider": "twilio", "sid": "SM123", "status": "queued"}


def test_provider_rejection_raises_not_records(creds, monkeypatch):
    """An unverified trial recipient comes back 400; the dashboard route maps
    HTTPError to a 502 and no sms row is written."""
    monkeypatch.setattr(sms_client.requests, "post",
                        lambda *a, **kw: _Resp(400, {"message": "unverified number"}))
    with pytest.raises(requests.HTTPError):
        sms_client.send_sms("+15550000001", "hi")
