"""Tool-first actions for the collections agent - the tool surface named
in server/agent/tool_registry.py. Shared by the live realtime voice agent
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


def effective_policy(debt: dict, policy: dict) -> dict:
    """Overlay this debt's per-customer repayment overrides onto the global
    policy defaults - a borrower with their own agreed terms (repayment %,
    floor %, cycle length) gets those instead of the policy row's."""
    merged = dict(policy)
    for key, col in (
        ("due_now_percent", "due_now_percent_override"),
        ("min_payment_today_percent", "min_payment_today_percent_override"),
        ("cycle_days", "cycle_days_override"),
    ):
        if debt.get(col) is not None:
            merged[key] = debt[col]
    return merged


# --- Read tools --------------------------------------------------------


def _debt_row(debt_id: str) -> dict:
    """Raw debt record for internal use - keeps amount_due as-is."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()
    debt = row_to_dict(row)
    if debt is None:
        return {"error": f"No debt found for id {debt_id}"}
    # The account reference is an identity secret; never hand it to the agent.
    debt.pop("account_ref", None)
    return debt


def get_debt_profile(debt_id: str) -> dict:
    """Agent-facing view. Deliberately does NOT expose a bare `amount_due`.

    The agent asks for one cycle's instalment, never the whole balance - but
    it reads whatever the tool returns, so a plain `amount_due: 50000` gets
    quoted verbatim as "fifty thousand is due". The field is renamed to make
    that impossible to do by accident, and the instalment is attached here so
    the right number is present whichever tool the agent reaches for.
    """
    debt = _debt_row(debt_id)
    if "error" in debt:
        return debt

    policy = effective_policy(debt, _get_policy())
    t = offer_engine.payment_targets(debt["amount_due"], debt["amount_collected"], policy)
    total = debt.pop("amount_due")
    debt.pop("due_now_percent_override", None)
    debt.pop("min_payment_today_percent_override", None)
    debt.pop("cycle_days_override", None)
    debt["total_balance_DO_NOT_QUOTE"] = total
    debt["due_today_ASK_FOR_THIS"] = t["due_now"]
    debt["minimum_acceptable_today"] = t["floor"]
    debt["guidance"] = (
        f"Ask for ${t['due_now']:g} today - this cycle's instalment. Do NOT say the total balance "
        f"of ${t['remaining']:g}. Never accept less than ${t['floor']:g}."
    )
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
    debt = _debt_row(debt_id)
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
    debt = _debt_row(debt_id)
    if "error" in debt:
        return debt
    policy = effective_policy(debt, _get_policy())
    # Returns the full picture (due_now, floor, offers, below_floor) rather
    # than a bare list - the agent needs the floor to know when to stop.
    return offer_engine.generate_offer_options(
        debt["amount_due"],
        debt["amount_collected"],
        policy,
        borrower_can_pay_today,
    )


def apply_discount(debt_id: str, requested_pct: float) -> dict:
    debt = _debt_row(debt_id)
    if "error" in debt:
        return debt
    policy = _get_policy()
    remaining = max(0.0, round(debt["amount_due"] - debt["amount_collected"], 2))
    settled = offer_engine.apply_discount(remaining, requested_pct, policy)
    if settled is None:
        reason = (
            f"requested discount cannot be negative ({requested_pct}%)"
            if requested_pct < 0
            else f"requested {requested_pct}% exceeds max {policy['max_discount_percent']}%"
        )
        return {"approved": False, "reason": f"{reason} - route to human review"}
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


def send_sms_payment_link(debt_id: str, amount: float, reason: str = "", live: bool | None = None) -> dict:
    """Create a payment link and text it.

    `live` decides whether a real SMS goes out. The agent calls this during
    an actual conversation and passes live=True - a borrower who has just
    agreed to pay must actually receive the link. The simulator and the
    demo-clock scheduler leave it None, falling back to A1MOBILE_LIVE_SMS,
    so replaying 30 days of activity never texts anyone.
    """
    debt = _debt_row(debt_id)
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

    should_send = config.A1MOBILE_LIVE_SMS if live is None else live
    sent_live = False
    if should_send:
        a1mobile_client.send_sms(to=debt["phone"], body=body)
        sent_live = True

    return {"sms_id": sms_id, "payment_id": payment_id, "payment_link": link_path, "payment_status": "sent", "sent_live": sent_live}


def schedule_sms_reminder(debt_id: str, send_at: str, message_type: str = "reminder") -> dict:
    debt = _debt_row(debt_id)
    if "error" in debt:
        return debt
    with get_conn() as conn:
        conn.execute(
            "UPDATE debts SET next_action = 'send_sms_reminder', next_action_at = ? WHERE id = ?",
            (send_at, debt_id),
        )
    return {"debt_id": debt_id, "next_action": "send_sms_reminder", "next_action_at": send_at, "message_type": message_type}


def schedule_next_action(debt_id: str, next_action: str, next_action_at: str, reason: str = "") -> dict:
    debt = _debt_row(debt_id)
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
    debt = _debt_row(debt_id)
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
    return _debt_row(debt_id)


def write_memory(debt_id: str, key: str, value: str) -> dict:
    # Never persist protected traits, insults, or speculative labels - a
    # later call overwrites a stale fact under the same key instead.
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
    debt = _debt_row(debt_id)
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
    return _debt_row(debt_id)


def send_sms_reminder(debt_id: str) -> dict:
    """Scheduler executor for the 'send_sms_reminder' action - distinct from
    the schedule_sms_reminder agent tool, which only books it."""
    debt = _debt_row(debt_id)
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
    debt = _debt_row(debt_id)
    if "error" in debt:
        return debt
    with get_conn() as conn:
        conn.execute("UPDATE debts SET next_action_at = NULL WHERE id = ?", (debt_id,))
    return {"debt_id": debt_id, "status": debt["status"], "amount_collected": debt["amount_collected"]}


def send_sms_now(debt_id: str, body: str | None = None, sms_type: str = "custom", amount: float | None = None) -> dict:
    """Send an SMS to the borrower for real, right now, and record it.

    Deliberately not gated behind config.A1MOBILE_LIVE_SMS the way
    send_sms_payment_link is. That gate exists so scheduled replays and the
    simulator never text anyone by accident; this function is only reached
    from an explicit human click in the dashboard, where actually sending is
    the whole point.

    With sms_type="payment_link" a real payment record is minted and its URL
    appended, so the link works in the mock checkout like any other.
    """
    debt = _debt_row(debt_id)
    if "error" in debt:
        return debt
    if not debt.get("phone"):
        return {"error": f"{debt['name']} has no phone number on file"}

    remaining = round(debt["amount_due"] - debt["amount_collected"], 2)
    payment_id = link_path = None

    if sms_type == "payment_link":
        amount = remaining if amount is None else amount
        payment_id = f"pay_{uuid.uuid4().hex[:8]}"
        link_path = f"/pay/{payment_id}"
        link_url = f"{config.PUBLIC_BASE_URL}{link_path}" if config.PUBLIC_BASE_URL else link_path
        body = (body or f"Pay ${amount:g} here:") + f" {link_url}"
    elif not body:
        body = f"Reminder from SettleWise: ${remaining:g} is outstanding on your account."

    # Send before recording, so a rejected message (e.g. a number that was
    # never OTP-verified) surfaces as an error instead of a phantom row.
    send_result = a1mobile_client.send_sms(to=debt["phone"], body=body)

    sms_id = f"sms_{uuid.uuid4().hex[:8]}"
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sms_messages (id, debt_id, payment_id, sent_at, type, amount, body, payment_link, payment_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'sent')""",
            (sms_id, debt_id, payment_id, _now_iso(), sms_type, amount, body, link_path),
        )

    return {
        "sms_id": sms_id,
        "to": debt["phone"],
        "name": debt["name"],
        "body": body,
        "type": sms_type,
        "payment_link": link_path,
        "sent_live": True,
        "provider": send_result,
    }


def flag_borrower(debt_id: str, reason: str, severity: str = "warning") -> dict:
    """Record a conduct problem (abuse, threats, refusing to engage) on the
    profile so the next person to pick this up sees it before dialling.

    severity "warning" notes it but leaves the account collectable;
    "abuse" also suspends automated collection by routing to human review.
    """
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO memory (id, debt_id, key, value, learned_at) VALUES (?, ?, 'conduct_flag', ?, ?)",
            (f"mem_{uuid.uuid4().hex[:8]}", debt_id, f"[{severity}] {reason}", _now_iso()),
        )
        if severity == "abuse":
            conn.execute(
                "UPDATE debts SET status = 'needs_review', next_action = 'human_review', "
                "next_action_at = NULL, last_call_summary = ? WHERE id = ?",
                (f"Call ended early - {reason}", debt_id),
            )
    return {"debt_id": debt_id, "flagged": True, "severity": severity, "reason": reason}


def get_payment_history(debt_id: str) -> dict:
    """What has actually been sent and paid on this account.

    Without this the agent can't answer the two most common pushbacks -
    "I already paid" and "you never sent me anything" - and would have to
    either guess or take the borrower's word for it.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, payment_id, sent_at, type, amount, payment_status, payment_link "
            "FROM sms_messages WHERE debt_id = ? ORDER BY sent_at",
            (debt_id,),
        ).fetchall()
    debt = _debt_row(debt_id)
    if "error" in debt:
        return debt
    return {
        "amount_due": debt["amount_due"],
        "amount_collected": debt["amount_collected"],
        "outstanding": round(debt["amount_due"] - debt["amount_collected"], 2),
        "messages": [dict(r) for r in rows],
    }
