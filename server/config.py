import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

A1MOBILE_BASE_URL = os.getenv("A1MOBILE_BASE_URL", "https://hack.a1mobile.com")
A1MOBILE_TEAM_KEY = os.getenv("A1MOBILE_TEAM_KEY", "")
A1MOBILE_PHONE_NUMBER = os.getenv("A1MOBILE_PHONE_NUMBER", "")

# SIP credentials from /api/numbers/claim. a1mobile itself has no outbound
# calling, but these can be registered as a Vapi BYO SIP trunk to dial out.
A1MOBILE_SIP_USERNAME = os.getenv("A1MOBILE_SIP_USERNAME", "")
A1MOBILE_SIP_PASSWORD = os.getenv("A1MOBILE_SIP_PASSWORD", "")

# Vapi (outbound calling). VAPI_PRIVATE_KEY is set by hand; the three ids are
# written by `python -m server.vapi_setup setup`.
VAPI_PRIVATE_KEY = os.getenv("VAPI_PRIVATE_KEY", "")
VAPI_CREDENTIAL_ID = os.getenv("VAPI_CREDENTIAL_ID", "")
VAPI_PHONE_NUMBER_ID = os.getenv("VAPI_PHONE_NUMBER_ID", "")
VAPI_ASSISTANT_ID = os.getenv("VAPI_ASSISTANT_ID", "")

# No trailing slash, e.g. https://abcd1234.ngrok-free.app
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# Gate on actually sending SMS through a1mobile. Off by default: md/product-brief.md
# and md/mvp-scope.md list "no real outbound SMS/calling" as a non-goal for the
# simulated demo loop. Flip to true only for the live verified-number demo call.
A1MOBILE_LIVE_SMS = os.getenv("A1MOBILE_LIVE_SMS", "false").lower() == "true"

# Hackathon AI gateway (HTTP-only, /responses endpoint) - not used for the
# voice agent itself since it can't proxy the realtime WebSocket API.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "") or None

# Direct OpenAI key for the realtime speech-to-speech voice agent (wss://api.openai.com).
OPENAI_REALTIME_API_KEY = os.getenv("OPENAI_REALTIME_API_KEY", "")
OPENAI_REALTIME_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1")

DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "settlewise.db"))
SEED_PATH = os.getenv("SEED_PATH", str(BASE_DIR / "data" / "seed.json"))

MAX_DISCOUNT_PCT = float(os.getenv("MAX_DISCOUNT_PCT", "15"))

# Demo clock (md/technical-spec.md) - fake controllable time so 30 days of
# collections activity can be compressed into a short demo.
DEMO_CLOCK_START = os.getenv("DEMO_CLOCK_START", "2026-08-01T09:00:00")
DEMO_CLOCK_TIMEZONE = os.getenv("DEMO_CLOCK_TIMEZONE", "America/Los_Angeles")
