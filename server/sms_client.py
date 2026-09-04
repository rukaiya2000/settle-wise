"""SMS via Twilio's REST API.

A single POST with `requests` rather than the twilio SDK: the SDK is ~57MB
unpacked, a fifth of the headroom under Vercel's bundle limit, for one
endpoint. The two callers in agent/tools.py depend only on send_sms(to, body).

Sending is additionally gated by config.LIVE_SMS at the call sites, so the
simulated demo loop never reaches this module.
"""

import requests

from . import config

TWILIO_API = "https://api.twilio.com/2010-04-01"


class SmsNotConfigured(RuntimeError):
    """Raised when a real send is requested without Twilio credentials, so
    LIVE_SMS=true on a half-configured deployment fails loudly."""


def send_sms(to: str, body: str) -> dict:
    missing = [
        name for name, val in (
            ("TWILIO_ACCOUNT_SID", config.TWILIO_ACCOUNT_SID),
            ("TWILIO_AUTH_TOKEN", config.TWILIO_AUTH_TOKEN),
            ("TWILIO_FROM_NUMBER", config.TWILIO_FROM_NUMBER),
        ) if not val
    ]
    if missing:
        raise SmsNotConfigured(f"SMS not configured - set {', '.join(missing)} before enabling LIVE_SMS.")

    r = requests.post(
        f"{TWILIO_API}/Accounts/{config.TWILIO_ACCOUNT_SID}/Messages.json",
        auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
        data={"To": to, "From": config.TWILIO_FROM_NUMBER, "Body": body},
        timeout=15,
    )
    # A rejection (unverified trial recipient, bad From, 10DLC block) comes
    # back as 4xx with a JSON message; raise so the caller surfaces it rather
    # than recording a text that never went out.
    r.raise_for_status()
    data = r.json()
    return {"provider": "twilio", "sid": data.get("sid"), "status": data.get("status")}
