"""Tool-first actions for the collections agent, matching the tool surface
in md/technical-spec.md. Shared by the live realtime voice agent
(server/agent/pipeline.py) and the deterministic simulator
(server/agent/simulated_call.py) that the demo-clock scheduler drives, so a
scheduled 30-day replay and a real phone call produce identical-shaped data.

The agent must never assert debt facts, offers, or payment status from its
own reasoning - every action here is a DB read/write, so the conversation
stays auditable and can't hallucinate numbers.
"""

import uuid

from .. import a1mobile_client, config, offer_engine
from ..db import get_conn, row_to_dict
from ..demo_clock import get_demo_now
from ..policy import get_policy as _get_policy

TERMINAL_STATUSES = {"paid", "needs_review"}


def _now_iso() -> str:
    return get_demo_now().isoformat()


# --- Read tools --------------------------------------------------------


def get_debt_profile(debt_id: str) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()
    debt = row_to_dict(row)
    if debt is None:
        return {"error": f"No debt found for id {debt_id}"}
    return debt


def get_memory(debt_id: str) -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM memory WHERE debt_id = ? ORDER BY learned_at DESC", (debt_id,)
        ).fetchall()
    return {"memory": [dict(r) for r in rows]}


def get_policy(policy_id: str | None = None) -> dict:
    return _get_policy(policy_id) if policy_id else _get_policy()


# --- Decision tools ------------------------------------------------------


def _calls_today(debt_id: str, today: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM calls WHERE debt_id = ? AND substr(started_at, 1, 10) = ?",
            (debt_id, today),
        ).fetchone()
    return row["n"]


def check_call_allowed(debt_id: str) -> dict:
    debt = get_debt_profile(debt_id)
    if "error" in debt:
        return debt
    if debt["status"] in TERMINAL_STATUSES:
        return {"allowed": False, "reason": f"status is {debt['status']}"}

    with get_conn() as conn:
        no_contact = conn.execute(
            "SELECT 1 FROM memory WHERE debt_id = ? AND key = 'no_contact' LIMIT 1", (debt_id,)
        ).fetchone()
    if no_contact:
        return {"allowed": False, "reason": "borrower requested no further contact"}

    policy = _get_policy()
    now = get_demo_now()
    hours = policy["allowed_call_hours"]
    if not (hours["start"] <= now.strftime("%H:%M") <= hours["end"]):
        return {"allowed": False, "reason": f"outside allowed call window {hours['start']}-{hours['end']}"}

    attempts_today = _calls_today(debt_id, now.strftime("%Y-%m-%d"))
    if attempts_today >= policy["call_attempts_per_day"]:
        return {"allowed": False, "reason": f"already made {attempts_today} attempts today (max {policy['call_attempts_per_day']})"}

    return {"allowed": True, "reason": "Within synthetic call window"}


def generate_offer_options(debt_id: str, borrower_can_pay_today: float | None = None) -> dict:
    debt = get_debt_profile(debt_id)
    if "error" in debt:
        return debt
    policy = _get_policy()
    with get_conn() as conn:
        has_income_date = (
            conn.execute(
                "SELECT 1 FROM memory WHERE debt_id = ? AND key = 'salary_date' LIMIT 1", (debt_id,)
            ).fetchone()
            is not None
            or bool(debt.get("salary_date"))
        )
    offers = offer_engine.generate_offer_options(
        debt["amount_due"], debt["amount_collected"], policy, borrower_can_pay_today, has_income_date
    )
    return {"offers": offers}


def apply_discount(debt_id: str, requested_pct: float) -> dict:
    debt = get_debt_profile(debt_id)
    if "error" in debt:
        return debt
    policy = _get_policy()
    remaining = round(debt["amount_due"] - debt["amount_collected"], 2)
    settled = offer_engine.apply_discount(remaining, requested_pct, policy)
    if settled is None:
        return {
            "approved": False,
            "reason": f"requested {requested_pct}% exceeds max {policy['max_discount_percent']}% - route to human review",
        }
    return {"approved": True, "settled_amount": settled}


# --- Action tools --------------------------------------------------------


def record_call_event(
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
        if amount_promised is not None:
            conn.execute("UPDATE debts SET amount_promised = ? WHERE id = ?", (amount_promised, debt_id))
    return {"call_id": call_id, "debt_id": debt_id, "outcome": outcome}


def send_sms_payment_link(debt_id: str, amount: float, reason: str = "") -> dict:
    debt = get_debt_profile(debt_id)
    if "error" in debt:
        return debt

    payment_id = f"pay_{uuid.uuid4().hex[:8]}"
    link_path = f"/pay/{payment_id}"
    link_url = f"{config.PUBLIC_BASE_URL}{link_path}" if config.PUBLIC_BASE_URL else link_path
    body = f"Pay ${amount:g} here: {link_url}"

    sms_id = f"sms_{uuid.uuid4().hex[:8]}"
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sms_messages (id, debt_id, payment_id, sent_at, type, amount, body, payment_link, payment_status)
            VALUES (?, ?, ?, ?, 'payment_link', ?, ?, ?, 'sent')""",
            (sms_id, debt_id, payment_id, _now_iso(), amount, body, link_path),
        )

    sent_live = False
    if config.A1MOBILE_LIVE_SMS:
        a1mobile_client.send_sms(to=debt["phone"], body=body)
        sent_live = True

    return {"sms_id": sms_id, "payment_id": payment_id, "payment_link": link_path, "payment_status": "sent", "sent_live": sent_live}


def schedule_sms_reminder(debt_id: str, send_at: str, message_type: str = "reminder") -> dict:
    debt = get_debt_profile(debt_id)
    if "error" in debt:
        return debt
    with get_conn() as conn:
        conn.execute(
            "UPDATE debts SET next_action = 'send_sms_reminder', next_action_at = ? WHERE id = ?",
            (send_at, debt_id),
        )
    return {"debt_id": debt_id, "next_action": "send_sms_reminder", "next_action_at": send_at, "message_type": message_type}


def schedule_next_action(debt_id: str, next_action: str, next_action_at: str, reason: str = "") -> dict:
    debt = get_debt_profile(debt_id)
    if "error" in debt:
        return debt
    with get_conn() as conn:
        conn.execute(
            "UPDATE debts SET status = 'scheduled', next_action = ?, next_action_at = ?, last_call_summary = ? WHERE id = ?",
            (next_action, next_action_at, reason, debt_id),
        )
    return {"scheduled": True, "debt_id": debt_id, "status": "scheduled", "next_action": next_action, "next_action_at": next_action_at}


def update_debt_status(
    debt_id: str,
    status: str,
    last_call_summary: str | None = None,
    next_action: str | None = None,
    next_action_at: str | None = None,
) -> dict:
    debt = get_debt_profile(debt_id)
    if "error" in debt:
        return debt

    fields, values = ["status = ?"], [status]
    if last_call_summary is not None:
        fields.append("last_call_summary = ?")
        values.append(last_call_summary)
    if next_action is not None:
        fields.append("next_action = ?")
        values.append(next_action)
    if next_action_at is not None:
        fields.append("next_action_at = ?")
        values.append(next_action_at)
    values.append(debt_id)

    with get_conn() as conn:
        conn.execute(f"UPDATE debts SET {', '.join(fields)} WHERE id = ?", values)
    return get_debt_profile(debt_id)


def write_memory(debt_id: str, key: str, value: str) -> dict:
    # md/memory-and-learning.md "Bad Memory": never persist protected traits,
    # insults, or speculative labels. "Let later calls overwrite stale facts."
    mem_id = f"mem_{uuid.uuid4().hex[:8]}"
    with get_conn() as conn:
        conn.execute("DELETE FROM memory WHERE debt_id = ? AND key = ?", (debt_id, key))
        conn.execute(
            "INSERT INTO memory (id, debt_id, key, value, learned_at) VALUES (?, ?, ?, ?, ?)",
            (mem_id, debt_id, key, value, _now_iso()),
        )
    return {"id": mem_id, "debt_id": debt_id, "key": key, "value": value}


def mark_needs_review(debt_id: str, reason: str) -> dict:
    memory_key = "dispute_signal" if "dispute" in reason.lower() else "review_signal"
    with get_conn() as conn:
        conn.execute(
            "UPDATE debts SET status = 'needs_review', next_action = 'human_review', next_action_at = NULL, last_call_summary = ? WHERE id = ?",
            (reason, debt_id),
        )
        conn.execute(
            "INSERT INTO memory (id, debt_id, key, value, learned_at) VALUES (?, ?, ?, ?, ?)",
            (f"mem_{uuid.uuid4().hex[:8]}", debt_id, memory_key, reason, _now_iso()),
        )
    return {"debt_id": debt_id, "status": "needs_review", "reason": reason}


# --- Internal helpers used by the scheduler/payment routes, not agent tools ---


def mark_paid(debt_id: str, amount: float, sms_id: str | None = None) -> dict:
    debt = get_debt_profile(debt_id)
    if "error" in debt:
        return debt
    amount_collected = round(debt["amount_collected"] + amount, 2)
    amount_promised = max(0.0, round(debt["amount_promised"] - amount, 2))
    status = "paid" if amount_collected >= debt["amount_due"] else debt["status"]
    with get_conn() as conn:
        conn.execute(
            "UPDATE debts SET amount_collected = ?, amount_promised = ?, status = ?, "
            "next_action = CASE WHEN ? = 'paid' THEN NULL ELSE next_action END, "
            "next_action_at = CASE WHEN ? = 'paid' THEN NULL ELSE next_action_at END "
            "WHERE id = ?",
            (amount_collected, amount_promised, status, status, status, debt_id),
        )
        if sms_id:
            conn.execute("UPDATE sms_messages SET payment_status = 'paid' WHERE id = ?", (sms_id,))
        conn.execute(
            """INSERT INTO sms_messages (id, debt_id, payment_id, sent_at, type, amount, body, payment_status)
            VALUES (?, ?, NULL, ?, 'confirmation', ?, ?, 'paid')""",
            (
                f"sms_{uuid.uuid4().hex[:8]}",
                debt_id,
                _now_iso(),
                amount,
                f"Payment received: ${amount:g}. Thank you.",
            ),
        )
    return get_debt_profile(debt_id)


def send_sms_reminder(debt_id: str) -> dict:
    """Scheduler executor for the 'send_sms_reminder' action - distinct from
    the schedule_sms_reminder agent tool, which only books it."""
    debt = get_debt_profile(debt_id)
    if "error" in debt:
        return debt

    remaining = round(debt["amount_due"] - debt["amount_collected"], 2)
    sms_id = f"sms_{uuid.uuid4().hex[:8]}"
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sms_messages (id, debt_id, sent_at, type, amount, body, payment_status)
            VALUES (?, ?, ?, 'reminder', ?, ?, 'sent')""",
            (sms_id, debt_id, _now_iso(), remaining, f"Reminder: ${remaining:g} is due. Reply or pay your link."),
        )

    if remaining <= 0:
        with get_conn() as conn:
            conn.execute(
                "UPDATE debts SET next_action = NULL, next_action_at = NULL WHERE id = ?", (debt_id,)
            )
        return {"sms_id": sms_id, "reminder_sent": True, "remaining": remaining}

    retry_at = (get_demo_now().replace(hour=18, minute=0, second=0, microsecond=0)).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE debts SET status = 'promised', next_action = 'call_borrower', next_action_at = ? WHERE id = ?",
            (retry_at, debt_id),
        )
    return {"sms_id": sms_id, "reminder_sent": True, "remaining": remaining, "next_call_at": retry_at}


def check_payment_status(debt_id: str) -> dict:
    """Scheduler executor placeholder - payment completion is driven by the
    mock /pay page or a simulated-call outcome, not a poll, so this just
    reports current state without side effects."""
    debt = get_debt_profile(debt_id)
    if "error" in debt:
        return debt
    with get_conn() as conn:
        conn.execute("UPDATE debts SET next_action_at = NULL WHERE id = ?", (debt_id,))
    return {"debt_id": debt_id, "status": debt["status"], "amount_collected": debt["amount_collected"]}
