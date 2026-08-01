"""Deterministic simulated call engine (md/implementation-checklist.md step 6:
"Build fake run-agent deterministic flow" before real voice integration).

Drives the exact same tools the live realtime agent uses
(server/agent/tools.py), so a call fired by the demo-clock scheduler and a
real a1mobile phone call produce identically-shaped calls/sms_messages/
memory/debts rows. Outcomes are seeded off debt_id + attempt number so a
given demo replay is reproducible, not actually random.
"""

import hashlib
from datetime import timedelta

from ..db import get_conn
from ..demo_clock import get_demo_now
from . import tools as agent_tools


def _seeded_fraction(seed: str) -> float:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return (int(digest, 16) % 10_000) / 10_000


def _call_count(debt_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM calls WHERE debt_id = ?", (debt_id,)).fetchone()
    return row["n"]


def _pick_outcome(seed: str, call_count: int) -> str:
    r = _seeded_fraction(seed)
    if call_count == 0:
        buckets = [("no_answer", 0.25), ("needs_review", 0.10), ("promised", 0.45), ("paid", 0.20)]
    elif call_count == 1:
        buckets = [("no_answer", 0.10), ("needs_review", 0.10), ("promised", 0.55), ("paid", 0.25)]
    else:
        buckets = [("no_answer", 0.05), ("needs_review", 0.15), ("promised", 0.30), ("paid", 0.50)]

    cumulative = 0.0
    for outcome, weight in buckets:
        cumulative += weight
        if r < cumulative:
            return outcome
    return buckets[-1][0]


def run_simulated_call(debt_id: str) -> dict:
    debt = agent_tools._debt_row(debt_id)
    if "error" in debt:
        return debt

    remaining = round(debt["amount_due"] - debt["amount_collected"], 2)
    if remaining <= 0:
        agent_tools.update_debt_status(debt_id, status="paid", next_action=None, next_action_at=None)
        return {"outcome": "already_paid"}

    now = get_demo_now()
    eligibility = agent_tools.check_call_allowed(debt_id)
    if not eligibility["allowed"]:
        retry_at = (now + timedelta(hours=1)).isoformat()
        agent_tools.schedule_next_action(
            debt_id, next_action="call_borrower", next_action_at=retry_at, reason=f"Retry: {eligibility['reason']}"
        )
        return {"outcome": "not_allowed", "reason": eligibility["reason"]}

    call_count = _call_count(debt_id)
    seed = f"{debt_id}:{call_count}"
    outcome = _pick_outcome(seed, call_count)

    if outcome == "no_answer":
        agent_tools.record_call_event(debt_id, outcome="no_answer", summary="Borrower did not answer.")
        agent_tools.update_debt_status(debt_id, status="no_answer", last_call_summary="No answer.")
        delay = timedelta(hours=4) if call_count == 0 else timedelta(days=1)
        agent_tools.schedule_next_action(
            debt_id, next_action="call_borrower", next_action_at=(now + delay).isoformat(), reason="Retry after no answer"
        )
        return {"outcome": "no_answer"}

    if outcome == "needs_review":
        summary = "Borrower disputed the amount owed."
        agent_tools.record_call_event(debt_id, outcome="needs_review", summary=summary)
        agent_tools.mark_needs_review(debt_id, reason="dispute: borrower says amount is wrong")
        return {"outcome": "needs_review"}

    # promised or paid
    frac = 1.0 if outcome == "paid" else 0.3 + _seeded_fraction(seed + ":amt") * 0.4  # 30-70%
    amount_today = remaining if outcome == "paid" else round(remaining * frac, 2)
    amount_remainder = round(remaining - amount_today, 2)
    promise_date = (now + timedelta(days=3 + int(_seeded_fraction(seed + ":date") * 5))).strftime("%Y-%m-%d")

    if amount_remainder > 0:
        summary = f"Borrower agreed to pay ${amount_today:g} today and ${amount_remainder:g} by {promise_date}."
    else:
        summary = f"Borrower agreed to pay the full ${amount_today:g} today."

    agent_tools.record_call_event(
        debt_id,
        outcome="promised",
        summary=summary,
        amount_promised=amount_today + amount_remainder,
        promise_date=promise_date if amount_remainder > 0 else None,
    )
    agent_tools.update_debt_status(debt_id, status="promised", last_call_summary=summary)
    if amount_remainder > 0:
        agent_tools.write_memory(debt_id, key="last_promise", value=f"${amount_today:g} today, ${amount_remainder:g} by {promise_date}")

    link_result = agent_tools.send_sms_payment_link(debt_id, amount=amount_today, reason="promised_today")

    if outcome == "paid":
        agent_tools.mark_paid(debt_id, amount_today, sms_id=link_result.get("sms_id"))
        return {"outcome": "paid", "amount": amount_today}

    reminder_at = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0).isoformat()
    agent_tools.schedule_sms_reminder(debt_id, send_at=reminder_at, message_type="payment_link_reminder")
    return {"outcome": "promised", "amount_today": amount_today, "amount_remainder": amount_remainder}
