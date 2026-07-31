# Memory and Learning

## Purpose

Memory helps SettleWise contact borrowers at better times, remember commitments, and avoid making borrowers repeat themselves. It must be structured, explainable, and safe.

## Good Memory

- Borrower gets paid on the 5th.
- Borrower prefers calls after work.
- Borrower asked to be contacted after 6 PM.
- Borrower promised to pay 200 on 2026-08-05.
- Borrower says the late fee is disputed.
- Borrower prefers Hindi.

## Bad Memory

Avoid storing or using sensitive traits unless required for explicit borrower support:

- Race, religion, caste, nationality, health status, or family status.
- Insults or subjective judgments.
- Speculative financial labels.
- Anything that could drive discriminatory treatment.

## Memory Lifecycle

1. Extract candidate memory from transcript.
2. Classify memory type.
3. Validate whether it is allowed to store.
4. Save with source, confidence, timestamp, and expiration.
5. Use memory only through approved retrieval paths.
6. Expire stale or low-confidence memory.

## Memory Types

| Type | Example | Use |
| --- | --- | --- |
| payment_timing | Salary on 5th | Schedule follow-up |
| call_preference | Prefers calls after 6 PM | Schedule calls |
| language_preference | Prefers Hindi | Localize messages |
| promise_to_pay | 200 on Aug 5 | Monitor commitment |
| dispute_signal | Says amount is wrong | Escalate and suppress collections |
| hardship_signal | Lost job | Offer hardship path |
| identity_issue | Wrong number | Suppress contact |

## Learning Loops

The system can learn:

- Which contact times improve response.
- Which call times convert by borrower segment.
- Which offer ladders improve payment completion.
- Which borrowers need earlier human escalation.

The system should not learn or optimize on protected classes or proxy features that create discriminatory outcomes.
