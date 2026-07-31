# Simple Data Model

For the hackathon, keep the database intentionally small. One table should contain the borrower plus debt state. Everything else is just a log of what the agent did.

## Tables

1. `debts`
2. `calls`
3. `sms_messages`
4. `memory`

That is enough for the demo loop: pick borrower, call, negotiate, send SMS link, update status, remember useful facts.

## `debts`

Main table. One row per borrower/debt.

| Field | Type | Example |
| --- | --- | --- |
| id | string | `debt_001` |
| name | string | `Riya Sharma` |
| phone | string | `+14155550123` |
| amount_due | number | `850` |
| due_date | date | `2026-08-05` |
| breach_date | date | `2026-08-10` |
| status | enum | `new`, `calling`, `promised`, `paid`, `needs_review` |
| salary_date | string | `5th of every month` |
| last_call_summary | text | `Can pay 300 today, rest after salary.` |
| next_action_at | datetime | `2026-08-05T10:00:00` |
| next_action | string | `Send SMS reminder` |

## `calls`

One row per voice call attempt.

| Field | Type | Example |
| --- | --- | --- |
| id | string | `call_001` |
| debt_id | string | `debt_001` |
| started_at | datetime | `2026-07-31T12:05:00` |
| outcome | enum | `answered`, `no_answer`, `callback`, `promised`, `paid`, `needs_review` |
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
| sent_at | datetime | `2026-07-31T12:10:00` |
| type | enum | `payment_link`, `reminder`, `confirmation` |
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

## Example Seed JSON

```json
{
  "debts": [
    {
      "id": "debt_001",
      "name": "Riya Sharma",
      "phone": "+14155550123",
      "amount_due": 850,
      "due_date": "2026-08-05",
      "breach_date": "2026-08-10",
      "status": "new",
      "salary_date": "5th of every month",
      "last_call_summary": "",
      "next_action_at": null,
      "next_action": "Call borrower"
    }
  ],
  "calls": [],
  "sms_messages": [],
  "memory": []
}
```

## Demo Query Examples

- Show all debts where `status = new`.
- Pick the highest `amount_due` with the nearest `breach_date`.
- Show the last call summary for the selected debt.
- Show SMS payment links where `payment_status = sent`.
- Show memory facts for a borrower before starting the next call.
