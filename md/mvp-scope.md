# MVP Scope

## MVP Thesis

Build the smallest impressive loop: upload/import debt records, have the agent pick who to call, negotiate by voice, send an SMS payment link, update memory, and show the next scheduled action.

## In Scope

- Seed borrower/debt rows into SQLite from a JSON fixture file.
- Score debts by urgency and likelihood to pay.
- Simulate outbound voice calls in-app.
- Use SMS only for payment links, confirmations, and reminders.
- Conduct voice-based repayment negotiation.
- Offer full payment, partial payment, installments, and discounts.
- Generate mock payment links.
- Record borrower responses, promises, and payment outcomes.
- Schedule follow-up reminders and callbacks.
- Show a lightweight human-review lane for weird or sensitive cases.
- Maintain conversation logs and agent reasoning summaries.

## Out of Scope for First MVP

- Real payment processor integration.
- Real outbound SMS or calling.
- Full compliance implementation.
- Multi-country support.
- Complex legal escalation.
- Production-grade CRM integration.

## MVP Channels

1. Voice conversation simulator.
2. SMS timeline for payment links, confirmations, and reminders.

For demo purposes, the voice call can be transcribed live into a side-by-side "Agent" and "Borrower" transcript, with SMS events shown underneath.

## Offer Ladder

| Priority | Offer | Conditions |
| --- | --- | --- |
| 1 | Amount due this cycle - `due_now_percent` of the outstanding balance (`due_now`), default 10% | Default first ask, repeating every `cycle_days` (default 5) until cleared |
| 2 | Partial payment today, negotiated down toward the floor | Borrower cannot pay the full `due_now` amount |
| 3 | Discount or settlement | Agent can apply simple rules, such as max 15 percent discount |
| 4 | Human review | Dispute, hardship, angry borrower, edge case, or offer falls below the floor |

`due_now_percent`, the floor (`min_payment_today_percent`), and `cycle_days` are per-customer configurable - set when adding a customer or edited later - and fall back to the policy default when unset. There is no separate discrete "installment plan" offer type; the recurring `due_now` cycle above is the mechanism.

## Success Metrics

- Recovery rate before breach.
- Payment-link click-through rate.
- Payment-link completion rate.
- Promise-to-pay kept rate.
- Human escalation rate.
- Demo debts resolved.
- Average expected recovery lift.
- Average time from first contact to payment.
