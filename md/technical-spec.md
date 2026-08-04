# Technical Spec

## Stack

Use Python for the backend and agent orchestration.

Suggested minimal stack:

- Python backend: `FastAPI`
- Local DB: SQLite, single file (`data/settlewise.db`)
- Agent/model calls: OpenAI
- Voice agent: OpenAI Realtime API or equivalent voice session layer
- Frontend: simple web app, probably React or plain HTML for demo speed
- Runtime state: read/write directly against SQLite per request - no separate in-memory cache

OpenAI docs to reference during implementation:

- Realtime API for low-latency voice conversations: https://platform.openai.com/docs/api-reference/realtime
- OpenAI quickstart and tool/function calling concepts: https://platform.openai.com/docs/quickstart

## System Shape

```text
Frontend
  Profiles page
  Person progress page
  Voice call UI / transcript view
        |
Python API
  SQLite DB service
  Policy service
  Agent orchestrator
  Tool handlers
  SMS mock service
  Payment mock service
        |
OpenAI
  Voice conversation model
  Optional summarization/reasoning calls
```

## Core Demo Flow

1. User opens profiles page.
2. User selects a debt profile.
3. User clicks `Run agent`.
4. Backend loads debt profile, memory, policy, and prior call history.
5. Backend starts a voice agent session.
6. Agent calls borrower and negotiates.
7. Agent uses tools to:
   - inspect debt
   - check policy
   - create offer
   - send SMS payment link
   - schedule reminder
   - schedule future call
   - write memory
   - update debt status
8. Person progress page updates with calls made, collected, promised, SMS links sent, and next action.

## SQLite DB

Keep this as one file for the hackathon:

```text
data/settlewise.db
```

Tables: `debts`, `calls`, `sms_messages`, `memory`, `policies`, `demo_clock`.

Use the simple schema from [data-model.md](./data-model.md).

Implementation notes:

- Create tables with `CREATE TABLE IF NOT EXISTS` on startup, and run any column migrations before serving requests.
- Open a connection per request/tool call rather than holding a long-lived connection or an in-memory cache.
- Use generated IDs like `debt_001`, `call_001`, `sms_001`.
- For demo reliability, seed deterministic synthetic data from a fixture file (see [data-model.md](./data-model.md)).
- Use `demo_clock.current_time` instead of the real system clock for all demo workflows.

## Synthetic Policy

The policy should be fake but structured. It gives the agent boundaries and makes the demo feel real.

Example policy:

```json
{
  "id": "policy_default",
  "max_discount_percent": 15,
  "due_now_percent": 10,
  "cycle_days": 5,
  "min_payment_today_percent": 5,
  "max_installments": 3,
  "call_attempts_per_day": 2,
  "allowed_call_hours": {
    "start": "09:00",
    "end": "20:00"
  },
  "human_review_triggers": [
    "wrong_person",
    "dispute",
    "discount_above_limit",
    "angry_borrower",
    "cannot_pay_anything"
  ]
}
```

`due_now_percent`, `min_payment_today_percent`, and `cycle_days` are defaults, not fixed - any debt can override them per-customer (nullable `*_override` columns on `debts`, see [data-model.md](./data-model.md)). A debt with no override falls back to this policy row.

Policy service responsibilities:

- decide whether a call can be made
- decide max discount
- decide allowed installment count
- decide whether a case needs review
- generate a simple offer ladder

## Agent Memory

Keep memory as small key-value facts tied to a debt/person.

Examples:

```json
{
  "id": "mem_001",
  "debt_id": "debt_001",
  "key": "salary_date",
  "value": "5th of every month",
  "learned_at": "2026-07-31T12:08:00"
}
```

Useful memory keys:

- `salary_date`
- `best_call_time`
- `preferred_installment_count`
- `payment_objection`
- `last_promise`
- `sms_reminder_time`

Memory rules:

- Store only facts useful for the next collection attempt.
- Keep values short and structured.
- Let later calls overwrite stale facts.
- Show memory on the person progress page so judges can see the agent learning.

## Agent Tool Surface

The voice agent should not directly edit the DB. It should call explicit tools.

### Read Tools

#### `get_debt_profile`

Returns debt profile, amount due, status, breach date, salary date, and last summary.

Input:

```json
{ "debt_id": "debt_001" }
```

#### `get_memory`

Returns memory facts for the selected person.

Input:

```json
{ "debt_id": "debt_001" }
```

#### `get_policy`

Returns the synthetic policy. Takes no input - always returns the default policy.

Input:

```json
{}
```

#### `get_payment_history`

What has actually been sent and paid on this account: every SMS payment link, its status, and how much has been collected. Call this before responding to "I already paid" or "you never sent me anything" - don't take either claim at face value, and don't contradict the borrower without checking first.

Input:

```json
{ "debt_id": "debt_001" }
```

Output:

```json
{
  "amount_due": 850,
  "amount_collected": 300,
  "outstanding": 550,
  "messages": [
    { "id": "sms_001", "payment_id": "pay_001", "sent_at": "2026-07-31T12:10:00", "type": "payment_link", "amount": 300, "payment_status": "paid", "payment_link": "/pay/pay_001" }
  ]
}
```

### Decision Tools

#### `check_call_allowed`

Checks whether the agent should call now.

Input:

```json
{ "debt_id": "debt_001" }
```

Output:

```json
{ "allowed": true, "reason": "Within synthetic call window" }
```

#### `generate_offer_options`

Returns allowed repayment options.

Input:

```json
{
  "debt_id": "debt_001",
  "borrower_can_pay_today": 60
}
```

Output:

```json
{
  "total_outstanding": 850,
  "due_now": 85,
  "minimum_acceptable_today": 42.5,
  "cycle_days": 5,
  "payments_to_clear": 10,
  "offers": [
    { "type": "due_now", "amount": 85, "note": "due today - ask for this. Payment is expected today, not spread over weeks." },
    { "type": "partial", "amount_today": 60, "short_this_cycle": 25 },
    { "type": "discount_settlement", "amount": 72.25, "max_discount_percent": 15 }
  ],
  "below_floor": false,
  "instruction": "They can pay 60, which is acceptable. Confirm it and send the payment link. Never accept less than 42.5."
}
```

`due_now`, `minimum_acceptable_today`, and `cycle_days` reflect this debt's own repayment terms if it has an override, otherwise the policy default (see [data-model.md](./data-model.md)). If `borrower_can_pay_today` is below the floor, `below_floor` is `true` and `offers` is empty - the agent should stop negotiating and call `mark_needs_review`, not counter.

#### `apply_discount`

Checks a requested settlement discount against `max_discount_percent` and returns the settled amount.

Input:

```json
{ "debt_id": "debt_001", "requested_pct": 10 }
```

Output:

```json
{ "approved": true, "settled_amount": 765 }
```

or, if the request exceeds policy:

```json
{ "approved": false, "reason": "requested 25% exceeds max 15% - route to human review" }
```

### Action Tools

#### `record_call_event`

Creates or updates a call record.

Input:

```json
{
  "debt_id": "debt_001",
  "outcome": "promised",
  "summary": "Borrower agreed to pay 300 today and 550 after salary.",
  "amount_promised": 850,
  "promise_date": "2026-08-05"
}
```

#### `send_sms_payment_link`

Creates a fake payment link and records an SMS event.

Input:

```json
{
  "debt_id": "debt_001",
  "amount": 300,
  "reason": "partial_payment_today"
}
```

Output:

```json
{
  "sms_id": "sms_001",
  "payment_link": "/pay/pay_001",
  "payment_status": "sent"
}
```

#### `send_sms`

Texts the borrower right now, during the call - e.g. to confirm in writing what was just agreed, or send something they asked to have in writing. Sends immediately to their real phone. Use `send_sms_payment_link` instead when the message is a payment link, and `schedule_sms_reminder` to book one for later.

Input:

```json
{
  "debt_id": "debt_001",
  "body": "Confirming: $300 today, $550 after your Aug 5 salary."
}
```

#### `schedule_sms_reminder`

Records a future reminder.

Input:

```json
{
  "debt_id": "debt_001",
  "send_at": "2026-08-05T09:00:00",
  "message_type": "salary_date_reminder"
}
```

#### `schedule_next_action`

Schedules a future workflow action, usually a voice call based on salary date, callback request, or missed promise.

Input:

```json
{
  "debt_id": "debt_001",
  "next_action": "call_borrower",
  "next_action_at": "2026-08-05T18:00:00",
  "reason": "Salary date callback"
}
```

#### `update_debt_status`

Updates the debt row.

Input:

```json
{
  "debt_id": "debt_001",
  "status": "promised",
  "last_call_summary": "Can pay 300 today, rest after salary.",
  "next_action": "send_sms_reminder",
  "next_action_at": "2026-08-05T09:00:00"
}
```

#### `write_memory`

Stores a learned fact.

Input:

```json
{
  "debt_id": "debt_001",
  "key": "salary_date",
  "value": "5th of every month"
}
```

#### `flag_borrower`

Records a conduct problem on the borrower's profile - abuse, threats, or flat refusal to engage after warnings - so whoever picks this up next sees it before dialling. Severity `warning` notes it while keeping the account collectable; `abuse` also suspends automated collection and routes to human review.

Input:

```json
{
  "debt_id": "debt_001",
  "reason": "Borrower used threatening language after being asked to stop.",
  "severity": "abuse"
}
```

#### `mark_needs_review`

Routes edge cases to human review.

Input:

```json
{
  "debt_id": "debt_001",
  "reason": "discount_above_limit"
}
```

## Agent Prompt Shape

The agent should get:

- role: voice collections agent
- current debt profile
- memory facts
- synthetic policy
- allowed tool list
- conversation objective
- fallback/escalation rules

Core behavior:

```text
You are SettleWise, a voice debt collection agent.
Always ask for the amount due this cycle first - 10 percent of the
outstanding balance (due_now), repeating every 5 days until the balance
clears. Never open by asking for the full outstanding balance.
If they push back, negotiate downward, but never below 5 percent of the
outstanding balance - that is the hard floor. Below it, stop negotiating
and escalate to human review.
Use SMS only for payment links, reminders, and confirmations.
Use tools for offers, SMS links, memory, status updates, and review.
Do not invent payment links, discounts, or status changes.
Keep the tone firm, concise, and respectful.
```

## Backend Endpoints

Minimum API:

```text
GET  /api/debts
POST /api/debts
GET  /api/debts/{debt_id}
POST /api/debts/{debt_id}/update
POST /api/debts/{debt_id}/run-agent
GET  /api/debts/{debt_id}/progress
POST /api/payments/{payment_id}/mark-paid
```

`POST /api/debts` creates a customer (name, phone, amount, dates, and optionally per-customer `due_now_percent`/`min_payment_today_percent`/`cycle_days`). `POST /api/debts/{debt_id}/update` edits those same repayment-term fields on an existing customer - only fields present in the body are changed; sending `null` clears an override back to the policy default.

Optional:

```text
GET  /api/debts/{debt_id}/memory
GET  /api/debts/{debt_id}/calls
GET  /api/debts/{debt_id}/sms
POST /api/debts/{debt_id}/simulate-no-answer
POST /api/debts/{debt_id}/simulate-promise
```

## What Else To Think About

### Demo State Machine

The product is fundamentally a state machine. The agent can hold the conversation and recommend the next step, but backend workflow code should own state transitions and scheduled retriggers.

Define a clean state flow:

```text
new -> calling -> promised -> paid
new -> calling -> needs_review
new -> calling -> no_answer -> new
promised -> paid
promised -> missed -> scheduled
```

This matters more than a complex DB.

Recommended states:

| State | Meaning |
| --- | --- |
| `new` | Debt has not been worked yet or is ready for another attempt |
| `scheduled` | A future call or SMS reminder is already planned |
| `calling` | Voice call is in progress |
| `no_answer` | Last call was not answered |
| `callback_requested` | Borrower asked to be called at a specific time |
| `promised` | Borrower promised payment |
| `link_sent` | SMS payment link was sent and payment is pending |
| `missed` | Promise date passed without payment |
| `paid` | Debt is settled for the demo |
| `needs_review` | Human should handle the case |

As built, only `new`, `scheduled`, `no_answer`, `promised`, `paid`, and `needs_review` are actually set as `debts.status` anywhere in the code (`server/agent/tools.py`, `simulated_call.py`, `routes/dashboard.py`). `calling`, `link_sent`, and `missed` were never wired up to any transition. `callback_requested` exists, but only as a `calls.outcome` value (`record_call_event`), not a `debts.status` - see [data-model.md](./data-model.md).

Recommended scheduled action types:

| Action | Meaning |
| --- | --- |
| `call_borrower` | Start/retry voice call |
| `send_payment_link` | Send SMS payment link |
| `send_sms_reminder` | Send SMS reminder |
| `check_payment_status` | Check if promised payment arrived |
| `human_review` | Stop automation and show review state |

### Call Retriggering

Retriggering should be driven by `next_action` and `next_action_at` on the `debts` row.

Do not make the voice agent responsible for deciding when the next call happens in freeform text. The agent can recommend a next action, but the backend should write a structured next action.

#### Retrigger Sources

There are four ways a call can be triggered:

1. Manual trigger from the profiles page: user clicks `Run agent`.
2. Scheduled retry: prior call was `no_answer` or `callback_requested`.
3. Promise follow-up: borrower promised payment but did not pay.
4. Reminder-to-call: borrower asked to be called near salary date.
5. Memory-driven workflow: prior memory says the borrower gets paid on a certain date/time.

#### Fields Needed On `debts`

The simple `debts` table already has enough:

```json
{
  "status": "scheduled",
  "next_action": "call_borrower",
  "next_action_at": "2026-08-01T15:00:00",
  "last_call_summary": "No answer. Retry tomorrow afternoon."
}
```

Optional fields if useful:

```json
{
  "call_attempts": 2,
  "last_called_at": "2026-07-31T12:05:00",
  "last_call_outcome": "no_answer"
}
```

For the hackathon, these can be computed from the `calls` table instead of stored directly.

#### Retry Rules

Use simple synthetic rules:

| Last outcome | Next action | Delay |
| --- | --- | --- |
| `no_answer` | `call_borrower` | 4 hours |
| `no_answer` twice | `call_borrower` | 1 day |
| `callback_requested` | `call_borrower` | borrower-provided time |
| `promised` but unpaid | `send_sms_reminder` | morning of promise date |
| SMS reminder ignored | `call_borrower` | same evening |
| `needs_review` | No auto-call | manual only |
| `paid` | No call | none |

#### Memory-Driven Scheduled Calls

Some workflows should use memory to set `next_action_at`.

Important memory keys:

- `salary_date`
- `best_call_time`
- `callback_requested_at`
- `sms_reminder_time`
- `last_promise_date`

Example: borrower says "I get paid on the 5th, call me that evening."

Agent should call tools in this order:

1. `write_memory` with `salary_date = 5th of every month`.
2. `write_memory` with `best_call_time = evening`.
3. `schedule_next_action` with `next_action = call_borrower` and `next_action_at = next 5th at 18:00`.
4. `update_debt_status` with `status = scheduled`.

The important distinction:

- Memory stores reusable facts.
- `next_action_at` stores the actual workflow trigger.

Memory alone should not trigger a call. A scheduled action triggers the call.

#### New Tool: `schedule_next_action`

Add this tool so the agent can request future workflow actions without directly editing the debt row.

Input:

```json
{
  "debt_id": "debt_001",
  "next_action": "call_borrower",
  "next_action_at": "2026-08-05T18:00:00",
  "reason": "Borrower gets salary on the 5th and asked for evening callback"
}
```

Output:

```json
{
  "scheduled": true,
  "debt_id": "debt_001",
  "status": "scheduled",
  "next_action": "call_borrower",
  "next_action_at": "2026-08-05T18:00:00"
}
```

Backend implementation:

```python
def schedule_next_action(debt_id, next_action, next_action_at, reason):
    debt = get_debt(debt_id)
    debt["status"] = "scheduled"
    debt["next_action"] = next_action
    debt["next_action_at"] = next_action_at
    debt["last_call_summary"] = reason
    save_db()
    return debt
```

#### Scheduler Loop

For a demo, this can be a backend function called every few seconds or only when the page loads.

```python
def get_due_actions(now):
    return [
        debt for debt in db["debts"]
        if debt["status"] not in ["paid", "needs_review"]
        and debt.get("next_action_at")
        and debt["next_action_at"] <= now
    ]
```

Then:

```python
for debt in get_due_actions(now):
    if debt["next_action"] == "call_borrower":
        enqueue_voice_call(debt["id"])
    elif debt["next_action"] == "send_sms_reminder":
        send_sms_reminder(debt["id"])
    elif debt["next_action"] == "check_payment_status":
        check_payment_status(debt["id"])
```

#### Manual Retrigger

The `Run agent` button should call:

```text
POST /api/debts/{debt_id}/run-agent
```

Backend behavior:

1. Load debt.
2. If status is `paid`, reject with `already paid`.
3. If status is `needs_review`, either reject or allow only with `force=true`.
4. Create a `calls` row with outcome `calling`.
5. Start voice session or simulated call.
6. Let the agent use tools.
7. Write final call outcome.
8. Update `debts.status`, `next_action`, and `next_action_at`.

#### Payment Follow-Up

Payment links should also affect retriggering.

If SMS link is sent:

```json
{
  "status": "link_sent",
  "next_action": "send_sms_reminder",
  "next_action_at": "2026-08-05T09:00:00"
}
```

If reminder is sent and payment is still not made by evening:

```json
{
  "status": "promised",
  "next_action": "call_borrower",
  "next_action_at": "2026-08-05T18:00:00"
}
```

If payment succeeds:

```json
{
  "status": "paid",
  "next_action": null,
  "next_action_at": null
}
```

#### Dashboard UX

On the profiles page, show:

- `Run agent`
- `Retry now`
- `Next action: Call borrower at 6 PM`

On the person progress page, show:

- call attempts
- last outcome
- next scheduled call/reminder
- button to manually retrigger

This makes retriggering visible and controllable during the demo.

### Demo Clock

The demo needs a controllable system clock so you can show N days of agent progress in a few seconds.

All workflow code should use:

```python
now = get_demo_now()
```

instead of:

```python
datetime.now()
```

#### Clock State

Store the clock in JSON:

```json
{
  "demo_clock": {
    "current_time": "2026-08-01T09:00:00",
    "speed": "paused"
  }
}
```

Optional:

```json
{
  "demo_clock": {
    "current_time": "2026-08-01T09:00:00",
    "speed": "1_day_per_click",
    "timezone": "America/Los_Angeles"
  }
}
```

#### Clock Controls

Add simple backend endpoints:

```text
GET  /api/demo-clock
POST /api/demo-clock/set
POST /api/demo-clock/advance
POST /api/demo-clock/reset
```

Example advance request:

```json
{
  "amount": 1,
  "unit": "day"
}
```

Example response:

```json
{
  "current_time": "2026-08-02T09:00:00",
  "actions_fired": [
    {
      "debt_id": "debt_001",
      "action": "send_sms_reminder"
    },
    {
      "debt_id": "debt_002",
      "action": "call_borrower"
    }
  ]
}
```

#### Advance Algorithm

When the clock moves forward, the backend should process every due scheduled action between the old time and the new time.

```python
def advance_clock(amount, unit):
    old_now = get_demo_now()
    new_now = add_time(old_now, amount, unit)
    db["demo_clock"]["current_time"] = new_now

    fired = process_due_actions(until=new_now)
    save_db()
    return {
        "current_time": new_now,
        "actions_fired": fired,
    }
```

Important rule:

```text
Advancing the clock should trigger scheduled actions in order.
```

For example:

```text
Day 1 09:00 - Voice call
Day 1 09:05 - SMS payment link
Day 2 09:00 - SMS reminder
Day 2 18:00 - Retry voice call if unpaid
Day 5 18:00 - Salary-date callback
```

If the user advances from Day 1 to Day 6, the backend should process all due actions in chronological order so the progress page looks like the agent actually worked across the week.

#### Scheduler With Demo Clock

Use the demo clock in the scheduler:

```python
def process_due_actions(until):
    due = sorted(
        [
            debt for debt in db["debts"]
            if debt["status"] not in ["paid", "needs_review"]
            and debt.get("next_action_at")
            and debt["next_action_at"] <= until
        ],
        key=lambda debt: debt["next_action_at"],
    )

    fired = []
    for debt in due:
        action = debt["next_action"]
        if action == "call_borrower":
            run_agent_for_debt(debt["id"], mode="scheduled")
        elif action == "send_sms_reminder":
            send_sms_reminder(debt["id"])
        elif action == "check_payment_status":
            check_payment_status(debt["id"])
        fired.append({"debt_id": debt["id"], "action": action})

    return fired
```

#### Dashboard UX

Add a small clock control to the demo:

```text
Demo date: Aug 1, 2026 09:00

[+ 1 hour] [+ 1 day] [+ 3 days] [Reset]
```

When the user clicks `+ 1 day`:

1. Clock advances.
2. Scheduler fires due actions.
3. Calls/SMS/payment checks are appended to the selected person's timeline.
4. Profile statuses and progress metrics update.

This gives you a full N-day demo without waiting for real time.

### Call Simulation Mode

Decide whether the first hackathon version uses:

- fully simulated transcript
- user-typed borrower responses
- browser speech input/output
- true realtime voice

Build the UI so you can fake this cleanly if the voice API integration is not ready.

### Payment Simulation

You need a fake payment page or button:

```text
/pay/{payment_id}
```

Clicking `Pay` should update:

- `sms_messages.payment_status = paid`
- `debts.amount_collected`
- `debts.amount_promised`
- `debts.status = paid` if enough is collected
- person progress metrics

### Progress Calculation

Person progress page should compute:

- `amount_due`
- `amount_collected`
- `amount_promised`
- `calls_made`
- `sms_links_sent`
- `next_action`

Do not overbuild analytics yet.

### Synthetic Data Quality

Create 5-8 good demo profiles with different stories:

- pays fully
- partial today plus salary-date remainder
- no answer first, picks up later
- asks for discount
- needs human review
- already paid after SMS link

### Observability For Demo

Show the agent's reasoning lightly:

- selected strategy
- tools called
- memory written
- next action

This helps judges understand what is happening.

### Failure Paths

Have visible demo states for:

- no answer
- payment link sent but unpaid
- borrower asks for too much discount
- wrong person / needs review

### Configuration

Keep config in one place:

```text
.env   # read via server/config.py (os.getenv)
```

Policy and demo-clock values live as rows in the SQLite `policies` and `demo_clock` tables, not separate config files - see [data-model.md](./data-model.md).

### Testing

Useful tiny tests:

- SQLite read/write does not corrupt the DB file.
- offer generation respects max discount.
- `mark-paid` updates debt status.
- `run-agent` creates a call record.
- SMS payment link creates an `sms_messages` row.

## Build Order

1. Create the SQLite schema and seed fixture.
2. Implement the DB service (SQLite).
3. Implement policy service.
4. Implement tool handlers.
5. Implement fake `run-agent` flow with deterministic transcript.
6. Build profiles page.
7. Build person progress page.
8. Add OpenAI voice integration.
9. Add memory extraction.
10. Polish demo stories and edge cases.
