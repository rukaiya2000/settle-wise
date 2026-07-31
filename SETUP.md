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
```

Then call `+14108011742` (the claimed a1mobile number) from that phone.

## How the voice call is wired

`server/routes/voice.py` exposes:

- `POST /voice` - a1mobile's webhook target. Responds with TeXML pointing a
  `<Stream>` at `wss://.../ws` (mirrors Telnyx's Media Streaming handshake,
  since a1mobile's SIP host is `sip.telnyx.com`).
- `WS /ws` - the actual audio stream. Pipecat's `create_transport()` auto-detects
  the provider from the handshake and builds the right frame serializer, so
  this isn't hard-locked to Telnyx's exact wire format.

**This hasn't been confirmed against a1mobile's own docs** (only their curl
examples were available) - watch the server logs on your first real test
call. If the handshake doesn't match what's expected, `voice_webhook` logs
the raw payload so the TeXML response or `/ws` parsing can be adjusted.

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

- `GET /api/debts`, `GET /api/debts/{id}` - borrower state, call/SMS/memory history
- `GET /pay/{payment_id}` + `POST /pay/{payment_id}/complete` - mock checkout,
  matches `md/system-architecture.md`'s fake `/pay/:paymentId` flow

`server/agent/tools.py`'s `create_payment_link` only sends a real SMS through
a1mobile when `A1MOBILE_LIVE_SMS=true` in `.env`; otherwise it just logs the
`sms_messages` row, keeping the default loop simulated per the MVP scope.
