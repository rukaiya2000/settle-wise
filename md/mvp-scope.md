# MVP Scope

## MVP Thesis

Build the smallest impressive loop: upload/import debt records, have the agent pick who to call, negotiate by voice, send an SMS payment link, update memory, and show the next scheduled action.

## In Scope

- Seed borrower/debt rows from a local JSON, CSV, or simple database.
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
| 1 | Full payment today | Default first ask |
| 2 | Partial payment today plus remainder before breach | Borrower cannot pay full |
| 3 | Installment plan | Debt is eligible and borrower has future income date |
| 4 | Discount or settlement | Agent can apply simple rules, such as max 15 percent discount |
| 5 | Human review | Dispute, hardship, angry borrower, or edge case |

## Success Metrics

- Recovery rate before breach.
- Payment-link click-through rate.
- Payment-link completion rate.
- Promise-to-pay kept rate.
- Human escalation rate.
- Demo debts resolved.
- Average expected recovery lift.
- Average time from first contact to payment.
