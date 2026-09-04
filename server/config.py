import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Vapi (outbound calling). VAPI_PRIVATE_KEY is set by hand, VAPI_ASSISTANT_ID
# is written by `python -m server.vapi_setup setup`, and VAPI_PHONE_NUMBER_ID
# is the Vapi-hosted number to dial from (`vapi_setup numbers` lists them).
VAPI_PRIVATE_KEY = os.getenv("VAPI_PRIVATE_KEY", "")
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

# Twilio, for SMS (server/sms_client.py). All three must be set for a real
# send; LIVE_SMS gates whether one is attempted at all. Off by default so
# the simulated demo loop never texts anyone.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
LIVE_SMS = os.getenv("LIVE_SMS", "false").lower() == "true"

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

# Set DATABASE_URL to run on Postgres (Supabase, on the deployed instance);
# leave it unset and everything uses the local SQLite file as before. Use
# Supabase's *transaction pooler* (port 6543) rather than the direct 5432
# connection - serverless opens many short-lived connections and will
# exhaust the direct limit.
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Open the dashboard and the harmless writes to anyone with the link. The
# destructive and real-telephony routes stay behind the login either way
# (server/auth.py:PROTECTED_ALWAYS).
PUBLIC_DEMO = os.getenv("PUBLIC_DEMO", "false").lower() == "true"

# The voice stack (pipecat and its ~570MB of transitive deps: onnxruntime,
# llvmlite, cv2, av, numba) is only needed for the in-browser WebRTC demo; outbound calling through Vapi doesn't touch
# it, and the serverless deployment omits it to stay under the bundle size
# limit. Unset means "on if pipecat is installed" - so local dev keeps
# working untouched and the deploy turns it off by simply not shipping the
# package. Set explicitly to force either way.
ENABLE_VOICE = os.getenv("ENABLE_VOICE", "").lower() or None

# Serverless cold starts shouldn't re-run CREATE TABLE on every request; the
# schema is created once by scripts/migrate_to_postgres.py instead.
SKIP_DB_INIT = os.getenv("SKIP_DB_INIT", "false").lower() == "true"

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
