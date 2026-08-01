# SettleWise

**Demo:** [Watch the video](https://drive.google.com/file/d/1FQK06LwnZG5tMHFDqMI4hNMuSOa1bFVM/view?usp=sharing)

An AI collections agent that phones borrowers, negotiates a repayment inside
policy limits, and turns the agreement into a payment — built as a hackathon
demo.

The interesting part isn't that it can hold a phone conversation. It's that
**the agent can't invent anything**. Every figure it says, every offer it
makes, and every state change comes from a tool call against a real database,
and the limits are enforced in code rather than trusted to the prompt. Ask it
to accept less than the floor and there is literally no offer for it to make.

---

## What it does

Pick a borrower on the dashboard, click **Call borrower**, and their phone
rings. The agent:

1. Confirms who it's speaking to before disclosing anything about a debt
2. Looks up the account and states the instalment due **today** — not the
   whole balance
3. Negotiates downward if they push back, never below a hard floor
4. Texts a real payment link the borrower can tap and pay
5. Records the outcome, remembers useful facts (salary date, best time to
   call), and schedules the follow-up
6. Escalates to a human on a dispute, a refusal, abuse, or anything it
   isn't confident about

Afterwards the borrower's page shows the transcript alongside **what the
agent actually did** — a plain-English trace of every tool it called.

## Try it in 30 seconds, without a phone

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m server.seed
.venv/bin/uvicorn server.main:app --port 8787 --reload
```

Then either:

```bash
# Talk to the agent as the borrower, in text. Prints every tool call.
.venv/bin/python -m server.agent.console debt_002

# Or replay a week of collections activity in one request
curl -X POST http://127.0.0.1:8787/api/demo-clock/advance \
  -H "Content-Type: application/json" -d '{"amount":7,"unit":"day"}'
```

Dashboard: <http://127.0.0.1:8787/dashboard/>

Placing real calls needs credentials and a public URL — see
[SETUP.md](./SETUP.md). Test scenarios are in [TESTING.md](./TESTING.md).

---

## How a call works

```
Dashboard "Call borrower"
  → POST /api/debts/{id}/call
  → Vapi  ──SIP──→  Telnyx  ──PSTN──→  borrower's phone

  Vapi runs the voice loop and calls back for every tool:
  → POST /api/vapi/tools  →  tool_registry  →  tools.py  →  SQLite
  → POST /api/vapi/events (transcript + summary when the call ends)
```

**Why Vapi is in the middle.** The hackathon telephony provider (a1mobile)
has no outbound calling — confirmed four ways: no dial tool in its MCP
catalog, every REST endpoint guess 404s, Telnyx's own Dial API needs
credentials only a1mobile holds, and a raw SIP `INVITE` never completes
digest auth even though `REGISTER` succeeds. Registering a1mobile's SIP
credentials as a Vapi BYO trunk works, so Vapi dials and we keep the logic.

**Inbound is a different path.** Someone calling the claimed number hits
a1mobile's webhook at `/voice`, and our own Pipecat pipeline handles it with
OpenAI's realtime model. Same tools, same database, different voice stack.

## The guardrails are code, not vibes

`server/offer_engine.py` decides what's on the table. If the borrower offers
less than the floor it returns an **empty offer list** — the agent has
nothing to say yes to, no matter how it's pressured. The discount cap works
the same way.

Other things learned the hard way and now fixed in code rather than prose:

- `get_debt_profile` doesn't expose a bare `amount_due`. When it did, the
  agent quoted the full balance — a real tool result, just the wrong field.
- A borrower saying "no" isn't an offer of zero. Passing `0` used to trip
  the floor and skip negotiation entirely.
- Tool descriptions carry the rules too, because the model reads those even
  when it skims the prompt.

The prompt lives at [`server/agent/prompt.md`](./server/agent/prompt.md) and
*is* the prompt — edit it directly, no code change needed.

## Repository

| Path | What's in it |
| --- | --- |
| `server/agent/` | prompt, the 16-tool registry, tool implementations, the deterministic call simulator |
| `server/routes/` | dashboard API, Vapi webhooks, inbound voice, SMS, mock checkout |
| `server/offer_engine.py` | what may be offered — the enforced limits |
| `server/scheduler.py`, `demo_clock.py` | fake clock so 30 days replays in seconds |
| `dashboard/` | operator UI (no build step, plain JS) |
| `md/` | product and technical specs |

## The demo clock

Real collections play out over weeks. Advancing the clock fires every due
action through a **deterministic simulator** — calls, reminders, payment
links, follow-ups — so the dashboard fills with a week of plausible activity
in one request. Outcomes are seeded from the debt id, so a demo replays the
same way every time. Real calls are never triggered this way.

## Known limits

It's a hackathon build, and a few things are honest to say out loud:

- **Identity checking is a verbal confirmation only.** An account-reference
  check was built and then removed; third-party disclosure rules are the
  remaining protection.
- **No real money moves.** `/pay/{id}` is a mock checkout that updates the
  database.
- **Compliance is demo-grade.** The guardrails in
  [`md/compliance-guardrails.md`](./md/compliance-guardrails.md) are modelled
  on real collections practice but have had no legal review.
- **SMS and calls only reach OTP-verified numbers**, by the provider's rule.
