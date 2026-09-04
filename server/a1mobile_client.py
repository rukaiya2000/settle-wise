"""Thin wrapper around the hack.a1mobile.com hackathon telephony API."""

import requests

from . import config


def _headers(json_body: bool = False) -> dict:
    headers = {"X-Team-Key": config.A1MOBILE_TEAM_KEY}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def claim_number() -> dict:
    r = requests.post(f"{config.A1MOBILE_BASE_URL}/api/numbers/claim", headers=_headers())
    r.raise_for_status()
    return r.json()


def point_webhook(webhook_url: str) -> dict:
    r = requests.post(
        f"{config.A1MOBILE_BASE_URL}/api/numbers/point",
        headers=_headers(True),
        json={"webhook_url": webhook_url},
    )
    r.raise_for_status()
    return r.json()


def request_verification(phone: str) -> dict:
    r = requests.post(
        f"{config.A1MOBILE_BASE_URL}/api/verified-numbers",
        headers=_headers(True),
        json={"phone": phone},
    )
    r.raise_for_status()
    return r.json()


def confirm_verification(phone: str, code: str) -> dict:
    r = requests.post(
        f"{config.A1MOBILE_BASE_URL}/api/verified-numbers/confirm",
        headers=_headers(True),
        json={"phone": phone, "code": code},
    )
    r.raise_for_status()
    return r.json()


def send_sms(to: str, body: str) -> dict:
    """Sends a real SMS via a1mobile. `to` must already be a verified number
    on the a1mobile side (OTP flow) - see request_verification/confirm_verification.
    Callers in server/agent/tools.py additionally gate this behind
    config.A1MOBILE_LIVE_SMS so the simulated demo loop never sends real texts
    by accident."""
    r = requests.post(
        f"{config.A1MOBILE_BASE_URL}/api/sms",
        headers=_headers(True),
        json={"to": to, "body": body},
    )
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "claim":
        print(claim_number())
    elif cmd == "point":
        print(point_webhook(sys.argv[2]))
    elif cmd == "verify":
        print(request_verification(sys.argv[2]))
    elif cmd == "confirm":
        print(confirm_verification(sys.argv[2], sys.argv[3]))
    elif cmd == "sms":
        print(send_sms(sys.argv[2], sys.argv[3]))
    else:
        print(
            "Usage: python -m server.a1mobile_client "
            "{claim | point <webhook_url> | verify <phone> | confirm <phone> <code> | sms <to> <body>}"
        )
