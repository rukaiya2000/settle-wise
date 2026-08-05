# Simple Data Model

For the hackathon, keep the database intentionally small. One table should contain the borrower plus debt state. Everything else is just a log of what the agent did.

## Tables

1. `debts`
2. `calls`
3. `sms_messages`
4. `memory`
5. `demo_clock`

That is enough for the demo loop: pick borrower, call, negotiate, send SMS link, update status, remember useful facts.

## `debts`

Main table. One row per borrower/debt.

| Field | Type | Example |
| --- | --- | --- |
| id | string | `debt_001` |
| name | string | `Riya Sharma` |
| account_ref | string | `SW-6693-4520` - generated server-side on creation (`SW-XXXX-XXXX`), never client-supplied. Its last 4 digits are the identity-verification secret; stripped from every agent-facing tool response |
| phone | string | `+14155550123` - validated against an E.164-ish pattern on create/update |
| amount_due | number | `850` |
| amount_collected | number | `300` |
| amount_promised | number | `550` |
| due_date | date | `2026-08-05` - repayment cycle start, auto-set to the demo clock's date when the customer is added |
| status | enum | `new`, `scheduled`, `no_answer`, `promised`, `paid`, `needs_review` (`calling`, `link_sent`, `missed`, `callback_requested` are recommended in [technical-spec.md](./technical-spec.md) but no code path sets them today) |
| last_call_summary | text | `Can pay 300 today, rest after salary.` |
| next_action_at | datetime | `2026-08-05T10:00:00` |
| next_action | string | `call_borrower`, `send_payment_link`, `send_sms_reminder`, `check_payment_status`, `human_review` |
| due_now_percent_override | number, nullable | `15` |
| min_payment_today_percent_override | number, nullable | `7` |
| cycle_days_override | integer, nullable | `7` |

The three override fields are per-customer repayment terms, editable when adding or updating a debt. `NULL` (the default) means this borrower uses the `policies` row's `due_now_percent` / `min_payment_today_percent` / `cycle_days` instead - see `server/agent/tools.py:effective_policy`.

There is deliberately no `salary_date` (or `breach_date`) column - pre-filling a borrower's salary date before ever speaking to them was a privacy liability with no offsetting use in the negotiation logic. `salary_date` still exists as a `memory` key, learned live and only if the borrower volunteers it during a call.

## `calls`

One row per voice call attempt.

| Field | Type | Example |
| --- | --- | --- |
| id | string | `call_001` |
| debt_id | string | `debt_001` |
| started_at | datetime | `2026-07-31T12:05:00` |
| outcome | enum | `answered`, `no_answer`, `callback_requested`, `promised`, `paid`, `needs_review` |
| transcript | text | `Agent: ... Borrower: ...` |
| summary | text | `Borrower agreed to pay 300 today.` |
| amount_promised | number | `300` |
| promise_date | date | `2026-07-31` |

## `sms_messages`

SMS is only used for payment links, confirmations, and reminders.

| Field | Type | Example |
| --- | --- | --- |
| id | string | `sms_001` |
| debt_id | string | `debt_001` |
| payment_id | string | `pay_001` |
| sent_at | datetime | `2026-07-31T12:10:00` |
| type | enum | `payment_link`, `reminder`, `confirmation` |
| amount | number | `300` |
| body | text | `Pay 300 here: /pay/pay_001` |
| payment_link | string | `/pay/pay_001` |
| payment_status | enum | `none`, `sent`, `clicked`, `paid`, `expired` |

## `memory`

Tiny key-value store for facts learned during calls.

| Field | Type | Example |
| --- | --- | --- |
| id | string | `mem_001` |
| debt_id | string | `debt_001` |
| key | string | `best_call_time` |
| value | string | `after 6 PM` |
| learned_at | datetime | `2026-07-31T12:08:00` |

## `demo_clock`

One object, not a table. It controls fake time for the demo.

| Field | Type | Example |
| --- | --- | --- |
| current_time | datetime | `2026-08-01T09:00:00` |
| timezone | string | `America/Los_Angeles` |
| speed | string | `paused` |

## Example Seed Fixture (`data/seed.json`)

Loaded once by `seed.py` into the SQLite tables above via `INSERT OR REPLACE` - this file is a seed fixture, not the runtime database.

```json
{
  "debts": [
    {
      "id": "debt_001",
      "name": "Riya Sharma",
      "phone": "+14155550123",
      "amount_due": 850,
      "amount_collected": 0,
      "amount_promised": 0,
      "due_date": "2026-08-05",
      "status": "new",
      "last_call_summary": "",
      "next_action_at": null,
      "next_action": "call_borrower"
    }
  ],
  "calls": [],
  "sms_messages": [],
  "memory": [],
  "demo_clock": {
    "current_time": "2026-08-01T09:00:00",
    "timezone": "America/Los_Angeles",
    "speed": "paused"
  }
}
```

## Demo Query Examples

- Show all debts where `status = new`.
- Pick the highest `amount_due` with the earliest `due_date` (longest in collections).
- Show the last call summary for the selected debt.
- Show SMS payment links where `payment_status = sent`.
- Show memory facts for a borrower before starting the next call.
- Advance `demo_clock.current_time` by 1 day and process due actions.
