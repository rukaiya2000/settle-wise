# Implementation Checklist

This is the short list of pieces needed before building the hackathon demo.

## Must Build

- JSON DB at `data/settlewise.json`
- Synthetic seed data with 5-8 debt profiles
- Demo clock with `+1 hour`, `+1 day`, `+3 days`, and reset
- State machine transitions for `new`, `scheduled`, `calling`, `no_answer`, `callback_requested`, `promised`, `link_sent`, `missed`, `paid`, `needs_review`
- Tool handlers for agent actions
- Profiles page with `Run agent`, `Retry now`, and `View progress`
- Person progress page with calls, SMS history, memory, and key metrics
- Fake payment page or `mark paid` action

## Agent Tools

- `get_debt_profile`
- `get_memory`
- `get_policy`
- `check_call_allowed`
- `generate_offer_options`
- `record_call_event`
- `send_sms_payment_link`
- `schedule_sms_reminder`
- `schedule_next_action`
- `update_debt_status`
- `write_memory`
- `mark_needs_review`

## Key Backend Services

- `JsonDbService`
- `PolicyService`
- `StateMachineService`
- `DemoClockService`
- `SchedulerService`
- `AgentOrchestrator`
- `SmsMockService`
- `PaymentMockService`
- `MemoryService`

## Demo Decisions To Lock

- First version of voice: simulated transcript, browser speech, or true realtime voice
- Whether SMS is fully mocked or uses a provider in demo mode
- Exact synthetic policy values
- Exact demo start date
- Which 5-8 borrower stories to seed
- How much agent reasoning to show in the UI

## Suggested First Implementation Order

1. Build JSON DB and seed data.
2. Build state machine transitions.
3. Build demo clock and scheduler.
4. Build profiles page.
5. Build person progress page.
6. Build fake `run-agent` deterministic flow.
7. Build fake payment marking.
8. Add OpenAI voice integration.
9. Add memory extraction and scheduling from salary dates.
10. Polish demo stories.
