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

# Speech-to-speech: the model handles audio in and out itself, so there's no
# STT -> LLM -> TTS round trip between the borrower speaking and the agent
# replying. NOT the same name as OPENAI_REALTIME_MODEL - Vapi only accepts
# models from its own list and rejects "gpt-realtime-2.1".
# Set VAPI_MODEL=gpt-4.1 in .env to fall back to the cascade pipeline.
VAPI_MODEL = os.getenv("VAPI_MODEL", "gpt-realtime-2025-08-28")
# Realtime only supports OpenAI's own voices (alloy, echo, shimmer, marin,
# cedar); on a cascade model any provider works. VAPI_VOICE_PROVIDER lets
# you swap TTS without touching code if articulation is poor.
VAPI_VOICE = os.getenv("VAPI_VOICE", "alloy")
VAPI_VOICE_PROVIDER = os.getenv("VAPI_VOICE_PROVIDER", "openai")

# No trailing slash, e.g. https://abcd1234.ngrok-free.app
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# Gate on actually sending SMS through a1mobile. Off by default so the
# simulated demo loop never texts anyone; flip to true only for the live
# verified-number demo call.
A1MOBILE_LIVE_SMS = os.getenv("A1MOBILE_LIVE_SMS", "false").lower() == "true"

# Hackathon AI gateway (HTTP-only, /responses endpoint) - not used for the
# voice agent itself since it can't proxy the realtime WebSocket API.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "") or None
OPENAI_POST_CALL_MODEL = os.getenv("OPENAI_POST_CALL_MODEL", "gpt-5.6-sol")

# Direct OpenAI key for the realtime speech-to-speech voice agent (wss://api.openai.com).
OPENAI_REALTIME_API_KEY = os.getenv("OPENAI_REALTIME_API_KEY", "")
OPENAI_REALTIME_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1")
OPENAI_POST_CALL_API_KEY = os.getenv("OPENAI_POST_CALL_API_KEY", OPENAI_REALTIME_API_KEY or OPENAI_API_KEY)
OPENAI_POST_CALL_BASE_URL = os.getenv(
    "OPENAI_POST_CALL_BASE_URL",
    "https://api.openai.com/v1" if OPENAI_REALTIME_API_KEY else (OPENAI_BASE_URL or "https://api.openai.com/v1"),
)

DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "settlewise.db"))
SEED_PATH = os.getenv("SEED_PATH", str(BASE_DIR / "data" / "seed.json"))

MAX_DISCOUNT_PCT = float(os.getenv("MAX_DISCOUNT_PCT", "15"))

# What the agent actually collects on a call: DUE_NOW_PCT of the balance is
# due this cycle, and MIN_PAYMENT_PCT is a hard floor - anything below it is
# refused in code (server/offer_engine.py) and routed to a human, so the
# borrower can't negotiate the agent under it.
DUE_NOW_PCT = float(os.getenv("DUE_NOW_PCT", "10"))
MIN_PAYMENT_PCT = float(os.getenv("MIN_PAYMENT_PCT", "5"))
# The instalment repeats every CYCLE_DAYS until the balance is cleared,
# so 10% every 5 days settles a balance in 50 days.
CYCLE_DAYS = int(os.getenv("CYCLE_DAYS", "5"))

# Demo clock - fake controllable time so 30 days of collections activity
# can be compressed into a short demo.
DEMO_CLOCK_START = os.getenv("DEMO_CLOCK_START", "2026-08-01T09:00:00")
DEMO_CLOCK_TIMEZONE = os.getenv("DEMO_CLOCK_TIMEZONE", "America/Los_Angeles")
