# Human Review

## Why Human Review Exists in the Demo

Human review gives the demo a believable escape hatch. It shows that the agent can handle normal repayment conversations and route messy cases elsewhere.

## Queue Triggers

- Debt dispute.
- Fraud or identity theft claim.
- Wrong-party contact.
- Settlement request outside approved range.
- Agent uncertainty.
- Repeated failed negotiation.

## Review Packet

Each escalation should include:

- Debt ID and borrower name.
- Current balance and breach date.
- Contact history.
- Conversation transcript.
- Agent summary.
- Detected trigger.
- Offers shown.
- Payment links sent.
- Recommended next action.
- Agent reasoning.

## Reviewer Actions

- Approve settlement.
- Modify installment plan.
- Mark debt as `needs_review`.
- Mark wrong-party.
- Update contact permissions.
- Pause collections.
- Return to agent with constraints.

## SLA Ideas

| Trigger | Suggested SLA |
| --- | --- |
| Wrong-party contact | Now |
| Dispute | Today |
| Settlement exception | Same demo session |
| Low confidence | Same demo session |
