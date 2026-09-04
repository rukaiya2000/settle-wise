"""SMS provider seam.

No provider is wired. Texts are still recorded in sms_messages, and the demo
loop never sends them anyway (config.LIVE_SMS is off by default), so the
product works end to end without one. The two callers in agent/tools.py only
depend on this one signature; to go live, implement send_sms() here against
Twilio/Telnyx/etc. and nothing else changes.
"""


class SmsNotConfigured(RuntimeError):
    """Raised when a real send is requested and no provider is implemented,
    so LIVE_SMS=true without a provider fails loudly rather than pretending."""


def send_sms(to: str, body: str) -> dict:
    raise SmsNotConfigured(
        "No SMS provider is configured - implement server/sms_client.py:send_sms "
        "before setting LIVE_SMS=true."
    )
