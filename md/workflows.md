# Workflow Specs

## Debt Intake

1. Import borrower/debt rows into `debts`.
2. Normalize phone, timezone, and jurisdiction.
3. Validate required fields.
4. Resolve duplicates.
5. Set initial status to `new`.
6. Set `next_action` to `Call borrower`.

## Outreach Scheduling

1. Select candidate debts.
2. Run a lightweight contact eligibility check.
3. Rank by breach risk and payment likelihood.
4. Schedule a voice call based on urgency and best-known call time.
5. Prepare SMS follow-up for payment links and reminders.
6. Re-check eligibility immediately before sending.

## Voice Conversation

1. Start outbound voice call.
2. Confirm borrower is available to talk.
3. Confirm identity if debt details are needed.
4. Discuss amount due and due date.
5. Ask for full payment.
6. Negotiate approved alternative.
7. Generate SMS payment link.
8. Send the link by SMS during or immediately after the call.
9. Schedule SMS reminder if payment is not completed.

## Promise to Pay

1. Borrower gives amount and date.
2. Agent checks whether promise is acceptable.
3. Agent confirms details in writing.
4. Scheduler creates reminder before promise date.
5. System monitors payment completion.
6. If payment is missed, debt returns to prioritization.

## Dispute Handling

1. Borrower disputes debt or amount.
2. Agent acknowledges dispute.
3. Stop repayment negotiation.
4. Mark debt as `needs_review`.
5. Collect concise dispute reason.
6. Escalate to human or dispute operations.
7. Suppress normal collections until resolved.

## Hardship Handling

1. Borrower indicates inability to pay due to hardship.
2. Agent acknowledges without judgment.
3. Offer approved hardship options if available.
4. Escalate if hardship is severe, unclear, or outside policy.
5. Record hardship signal as protected memory.

## Payment Completion

1. Payment provider sends callback.
2. Match payment to SMS payment link and debt.
3. Update debt amount/status.
4. Send confirmation.
5. Cancel unnecessary follow-ups.
6. Write conversation event.
