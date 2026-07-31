# SettleWise setup

Hackathon collections-agent demo. Full spec in [`md/`](./md/README.md). This
covers getting the server running and the a1mobile number wired to it.

## 1. Install dependencies

Python 3.11 is required (Pipecat's audio deps don't yet support 3.14).

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`.env` already has the a1mobile team key, claimed number, the hackathon
gateway key, and a direct OpenAI key for the realtime voice model filled in.

## 2. Seed the database

```bash
.venv/bin/python -m server.seed
```

Creates `data/settlewise.db` (SQLite) from `data/seed.json`, matching the
`debts` / `calls` / `sms_messages` / `memory` tables in
[`md/data-model.md`](./md/data-model.md).

## 3. Run the server

```bash
.venv/bin/uvicorn server.main:app --reload --port 8787
```

Check `http://127.0.0.1:8787/health` and `http://127.0.0.1:8787/api/debts`.

## 4. Expose it publicly and point the a1mobile webhook

Install ngrok if you don't have it: `brew install ngrok`, then `ngrok config
add-authtoken <token>` (from ngrok.com).

```bash
ngrok http 8787
```

Copy the `https://...ngrok-free.app` URL it prints, put it in `.env` as
`PUBLIC_BASE_URL` (no trailing slash), restart the server, then point the
number's voice webhook at it:

```bash
.venv/bin/python -m server.a1mobile_client point "https://YOUR-NGROK-HOST/voice"
```

## 5. Verify a demo number and call it

Per the guardrail in `md/product-brief.md` ("no real outbound calling/SMS" as
a demo non-goal), the intended use of a1mobile here is a **live** channel for
your own verified phone standing in as the borrower - not cold outreach to
the seed data's fake numbers.

```bash
.venv/bin/python -m server.a1mobile_client verify "+1YOURNUMBER"
# check the SMS you receive for the code
.venv/bin/python -m server.a1mobile_client confirm "+1YOURNUMBER" "123456"
# optional: confirm the SMS side works too
.venv/bin/python -m server.a1mobile_client sms "+1YOURNUMBER" "hello from settlewise"
```

Then call the claimed a1mobile number (`A1MOBILE_PHONE_NUMBER` in `.env`) from
that phone. If `/api/numbers/point` ever 409s with "claim a number first",
the claim expired - re-run `.venv/bin/python -m server.a1mobile_client claim`,
update `A1MOBILE_PHONE_NUMBER` in `.env`, and point the webhook again.

## How the voice call is wired

`server/routes/voice.py` exposes:

- `POST /voice` - a1mobile's webhook target. Responds with TeXML pointing a
  `<Stream>` at `wss://.../ws`.
- `WS /ws` - the actual audio stream. Pipecat's `parse_telephony_websocket()`
  auto-detects the provider from the handshake, so this isn't hard-locked to
  Telnyx's exact wire format even though that's what a1mobile turned out to be.

**Confirmed against a real live call** (2026-07-31): a1mobile's handshake is
Telnyx Media Streaming-shaped, exactly as guessed from their SIP host
(`sip.telnyx.com`) - `parse_telephony_websocket` auto-detects it as `telnyx`
from the second WebSocket message with no changes needed.

One fix was required to get audio flowing at all: Pipecat's `create_transport()`
convenience path builds a `TelnyxFrameSerializer` with `auto_hang_up=True` by
default, which requires a real Telnyx `api_key`/`call_control_id` to hang up
via Telnyx's REST API on call end. We don't have Telnyx credentials - a1mobile
owns the underlying Telnyx call and tears it down itself - so that serializer
construction raised `ValueError`/`TypeError` before any audio flowed (call
would connect and go silent). `server/agent/pipeline.py`'s `run_bot()` now
builds the transport manually via `parse_telephony_websocket()` +
`TelnyxFrameSerializer(params=TelnyxFrameSerializer.InputParams(auto_hang_up=False))`
instead of delegating to `create_transport()` for the `telnyx` case.

With that fix, a full multi-turn conversation ran cleanly end to end (clean
logs, no errors, TTFB 0.2-1s per turn). Audio was choppy on that first real
call - no errors in the logs, so this reads as network jitter in the local
dev machine -> free ngrok tunnel -> a1mobile -> Telnyx -> PSTN chain rather
than a code bug. Worth trying if it recurs: a wired connection instead of
Wi-Fi, checking for other bandwidth-heavy apps/CPU load, a paid ngrok tier,
or eventually a real (non-tunnel) deployment near where a1mobile/Telnyx route
from.

The conversation itself (`server/agent/pipeline.py`) runs on OpenAI's
realtime speech-to-speech model (`OPENAI_REALTIME_MODEL`, direct API key -
the hackathon gateway is an HTTP-only Lambda Function URL and can't proxy a
WebSocket connection, so it isn't used here). Every debt fact, offer, payment
link, memory write, dispute, or escalation goes through a tool call in
`server/agent/tools.py` - the system prompt (`server/agent/prompt.py`) is
built directly from `md/agent-behavior.md` and `md/compliance-guardrails.md`
and instructs the model to never state numbers from its own reasoning.

## Simulated demo loop (no live call needed)

The dashboard/payment API works standalone against the seeded data:

- `GET /api/debts`, `GET /api/debts/{id}`, `GET /api/debts/{id}/progress` -
  borrower state, key metrics, call/SMS/memory history
- `POST /api/debts/{id}/run-agent` - manually trigger the deterministic
  simulated call engine (`server/agent/simulated_call.py`) for one debt
- `GET /pay/{payment_id}` + `POST /pay/{payment_id}/complete` (also exposed
  as `POST /api/payments/{payment_id}/mark-paid`) - mock checkout, matches
  `md/system-architecture.md`'s fake `/pay/:paymentId` flow

`server/agent/tools.py`'s `send_sms_payment_link` only sends a real SMS
through a1mobile when `A1MOBILE_LIVE_SMS=true` in `.env`; otherwise it just
logs the `sms_messages` row, keeping the default loop simulated per the MVP
scope.

## Demo clock (30 days in seconds)

Per `md/technical-spec.md`, all scheduling reads a fake, controllable clock
instead of real time, so a week+ of collections activity can be replayed in
one request:

```bash
curl http://127.0.0.1:8787/api/demo-clock
curl -X POST http://127.0.0.1:8787/api/demo-clock/advance \
  -H "Content-Type: application/json" -d '{"amount": 7, "unit": "day"}'
curl -X POST http://127.0.0.1:8787/api/demo-clock/reset
```

Advancing fires every debt's due `next_action` in chronological order
(`server/scheduler.py`) via the deterministic simulator - calls, SMS
reminders, payment links, and follow-ups all chain together the same way a
real week of agent activity would, without placing real calls. Outcomes are
seeded off `debt_id` + attempt number, so a given demo replay is
reproducible, not actually random. The live a1mobile/realtime voice call
(`/voice`, `/ws`) is a separate, explicit path for the one moment you want to
show a real phone call - `run-agent` and the clock never trigger it.

Policy limits (max discount, min payment-today %, installment cap, call
window, attempts/day) live in the `policies` table (`server/policy.py`),
seeded with a `policy_default` row on first `init_db()` - edit
`MAX_DISCOUNT_PCT` etc. in `.env` or the row directly to tune the demo.
