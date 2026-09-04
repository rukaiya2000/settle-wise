"""Scheduler loop - the demo clock's advance algorithm.

Fires every debt's due next_action, in chronological order, up to the
target time - this is what lets advancing the demo clock replay days of
collections activity in one call. enqueue_voice_call routes to the
deterministic simulator rather than a live phone call; a real call through
Vapi is a separate, explicit path.
"""

from .db import get_conn

MAX_ITERATIONS = 200


def get_due_actions(until_iso: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM debts
            WHERE status NOT IN ('paid', 'needs_review')
              AND next_action_at IS NOT NULL
              AND next_action_at <= ?
            ORDER BY next_action_at ASC""",
            (until_iso,),
        ).fetchall()
    return [dict(r) for r in rows]


def _fire_action(debt: dict) -> dict:
    from .agent import tools as agent_tools
    from .agent.simulated_call import run_simulated_call

    action = debt["next_action"]
    debt_id = debt["id"]

    if action == "call_borrower":
        return run_simulated_call(debt_id)
    if action == "send_sms_reminder":
        return agent_tools.send_sms_reminder(debt_id)
    if action == "check_payment_status":
        return agent_tools.check_payment_status(debt_id)
    if action == "human_review":
        return agent_tools.mark_needs_review(debt_id, reason="scheduled_human_review")

    # Unknown action - clear it so the loop can't spin forever on it.
    with get_conn() as conn:
        conn.execute("UPDATE debts SET next_action_at = NULL WHERE id = ?", (debt_id,))
    return {"skipped": action}


def process_due_actions(until) -> list[dict]:
    until_iso = until.isoformat() if hasattr(until, "isoformat") else until
    fired = []
    for _ in range(MAX_ITERATIONS):
        due = get_due_actions(until_iso)
        if not due:
            break
        debt = due[0]
        result = _fire_action(debt)
        fired.append({"debt_id": debt["id"], "action": debt["next_action"], "result": result})
    return fired
