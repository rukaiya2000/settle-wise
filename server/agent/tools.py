"""Tool-first actions for the collections agent (md/agent-behavior.md).

The LLM must never assert debt facts, offers, or payment status from its own
reasoning - every action here is a DB read/write or an outbound call, so the
conversation stays auditable and can't hallucinate numbers.
"""

import uuid
from datetime import datetime, timezone

from .. import a1mobile_client, config, offer_engine
from ..db import get_conn, row_to_dict

DISALLOWED_STATUSES = {"needs_review", "paid"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_debt(debt_id: str) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()
    debt = row_to_dict(row)
    if debt is None:
        return {"error": f"No debt found for id {debt_id}"}
    return debt


def check_contact_eligibility(debt_id: str) -> dict:
    debt = get_debt(debt_id)
    if "error" in debt:
        return debt
    if debt["status"] in DISALLOWED_STATUSES:
        return {"eligible": False, "reason": f"status is {debt['status']}"}
    with get_conn() as conn:
        no_contact = conn.execute(
            "SELECT 1 FROM memory WHERE debt_id = ? AND key = 'no_contact' LIMIT 1",
            (debt_id,),
        ).fetchone()
    if no_contact:
        return {"eligible": False, "reason": "borrower requested no further contact"}
    return {"eligible": True, "reason": ""}


def generate_offer_ladder(debt_id: str) -> dict:
    debt = get_debt(debt_id)
    if "error" in debt:
        return debt
    with get_conn() as conn:
        has_income_date = conn.execute(
            "SELECT 1 FROM memory WHERE debt_id = ? AND key = 'salary_date' LIMIT 1",
            (debt_id,),
        ).fetchone() is not None or bool(debt.get("salary_date"))
    ladder = offer_engine.build_offer_ladder(debt["amount_due"], has_income_date)
    return {"offers": [o.__dict__ for o in ladder]}


def apply_discount(debt_id: str, requested_pct: float) -> dict:
    debt = get_debt(debt_id)
    if "error" in debt:
        return debt
    settled = offer_engine.apply_discount(debt["amount_due"], requested_pct)
    if settled is None:
        return {
            "approved": False,
            "reason": f"requested {requested_pct}% exceeds max {config.MAX_DISCOUNT_PCT}% - route to human review",
        }
    return {"approved": True, "settled_amount": settled}


def create_payment_link(debt_id: str, amount: float, sms_type: str = "payment_link") -> dict:
    debt = get_debt(debt_id)
    if "error" in debt:
        return debt

    payment_id = f"pay_{uuid.uuid4().hex[:8]}"
    link_path = f"/pay/{payment_id}"
    link_url = f"{config.PUBLIC_BASE_URL}{link_path}" if config.PUBLIC_BASE_URL else link_path
    body = f"Pay ${amount:g} here: {link_url}"

    sms_id = f"sms_{uuid.uuid4().hex[:8]}"
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sms_messages (id, debt_id, sent_at, type, body, payment_link, payment_status)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sms_id, debt_id, _now_iso(), sms_type, body, link_path, "sent"),
        )

    sent_live = False
    if config.A1MOBILE_LIVE_SMS:
        a1mobile_client.send_sms(to=debt["phone"], body=body)
        sent_live = True

    return {"payment_id": payment_id, "payment_link": link_path, "body": body, "sent_live": sent_live}


def schedule_followup(debt_id: str, next_action_at: str, next_action: str) -> dict:
    debt = get_debt(debt_id)
    if "error" in debt:
        return debt
    with get_conn() as conn:
        conn.execute(
            "UPDATE debts SET next_action_at = ?, next_action = ? WHERE id = ?",
            (next_action_at, next_action, debt_id),
        )
    return {"debt_id": debt_id, "next_action_at": next_action_at, "next_action": next_action}


def write_memory(debt_id: str, key: str, value: str) -> dict:
    # md/memory-and-learning.md "Bad Memory": never persist protected traits,
    # insults, or speculative labels - only structured, explainable facts.
    mem_id = f"mem_{uuid.uuid4().hex[:8]}"
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO memory (id, debt_id, key, value, learned_at) VALUES (?, ?, ?, ?, ?)",
            (mem_id, debt_id, key, value, _now_iso()),
        )
    return {"id": mem_id, "debt_id": debt_id, "key": key, "value": value}


def mark_dispute(debt_id: str, reason: str) -> dict:
    with get_conn() as conn:
        conn.execute("UPDATE debts SET status = 'needs_review', next_action = 'Human review' WHERE id = ?", (debt_id,))
        conn.execute(
            "INSERT INTO memory (id, debt_id, key, value, learned_at) VALUES (?, ?, 'dispute_signal', ?, ?)",
            (f"mem_{uuid.uuid4().hex[:8]}", debt_id, reason, _now_iso()),
        )
    return {"debt_id": debt_id, "status": "needs_review", "reason": reason}


def escalate_human_review(debt_id: str, trigger: str, reasoning: str) -> dict:
    with get_conn() as conn:
        conn.execute("UPDATE debts SET status = 'needs_review', next_action = 'Human review' WHERE id = ?", (debt_id,))
    return {"debt_id": debt_id, "status": "needs_review", "trigger": trigger, "reasoning": reasoning}


def record_call_outcome(
    debt_id: str,
    outcome: str,
    summary: str,
    transcript: str = "",
    amount_promised: float | None = None,
    promise_date: str | None = None,
) -> dict:
    call_id = f"call_{uuid.uuid4().hex[:8]}"
    started_at = _now_iso()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO calls (id, debt_id, started_at, outcome, transcript, summary, amount_promised, promise_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (call_id, debt_id, started_at, outcome, transcript, summary, amount_promised, promise_date),
        )
        new_status = "promised" if outcome == "promised" else ("needs_review" if outcome == "needs_review" else outcome)
        conn.execute(
            "UPDATE debts SET last_call_summary = ?, status = ? WHERE id = ?",
            (summary, new_status, debt_id),
        )
    return {"call_id": call_id, "debt_id": debt_id, "outcome": outcome}
