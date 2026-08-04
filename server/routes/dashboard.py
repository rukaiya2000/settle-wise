"""Dashboard API backing the profiles/progress screens (md/dashboard-spec.md)."""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from ..agent import tools as agent_tools
from ..agent.simulated_call import run_simulated_call
from ..db import get_conn
from ..demo_clock import get_demo_now
from .. import offer_engine
from ..policy import get_policy
from .vapi import poll_vapi_call_until_ended
from ..seed import reset_db
from ..vapi_setup import place_call

router = APIRouter()


class DebtCreateRequest(BaseModel):
    name: str
    phone: str
    amount_due: float
    breach_date: str | None = None
    salary_date: str | None = None
    due_now_percent: float | None = None
    min_payment_today_percent: float | None = None
    cycle_days: int | None = None


class DebtUpdateRequest(BaseModel):
    due_now_percent: float | None = None
    min_payment_today_percent: float | None = None
    cycle_days: int | None = None


def _validate_repayment_terms(due_now_percent: float | None, min_payment_today_percent: float | None, cycle_days: int | None):
    """Shared validation for create/update - keeps a customer's per-cycle
    terms sane regardless of which endpoint set them."""
    if due_now_percent is not None and not (0 < due_now_percent <= 100):
        raise HTTPException(400, "due_now_percent must be between 0 and 100")
    if min_payment_today_percent is not None and not (0 < min_payment_today_percent <= 100):
        raise HTTPException(400, "min_payment_today_percent must be between 0 and 100")
    if (
        due_now_percent is not None
        and min_payment_today_percent is not None
        and min_payment_today_percent > due_now_percent
    ):
        raise HTTPException(400, "min_payment_today_percent cannot exceed due_now_percent")
    if cycle_days is not None and cycle_days <= 0:
        raise HTTPException(400, "cycle_days must be a positive integer")


@router.get("/api/debts")
def list_debts():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM debts ORDER BY breach_date").fetchall()
    return [dict(r) for r in rows]


@router.post("/api/debts")
def create_debt(req: DebtCreateRequest):
    if req.amount_due <= 0:
        raise HTTPException(400, "amount_due must be positive")
    _validate_repayment_terms(req.due_now_percent, req.min_payment_today_percent, req.cycle_days)

    debt_id = f"debt_{uuid.uuid4().hex[:8]}"
    # The repayment cycle starts today (the demo clock's today, not the
    # server's) rather than a manually-picked due date - due_now/cycle_days
    # count from whenever the customer is actually added.
    start_date = get_demo_now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO debts
            (id, name, phone, amount_due, due_date, breach_date, status, salary_date, next_action,
             due_now_percent_override, min_payment_today_percent_override, cycle_days_override)
            VALUES (?, ?, ?, ?, ?, ?, 'new', ?, 'call_borrower', ?, ?, ?)""",
            (
                debt_id, req.name, req.phone, req.amount_due, start_date, req.breach_date,
                req.salary_date, req.due_now_percent, req.min_payment_today_percent, req.cycle_days,
            ),
        )
    with get_conn() as conn:
        debt = conn.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()
    return dict(debt)


@router.post("/api/reset-demo")
def reset_demo():
    reset_db()
    return {"status": "reset"}


@router.get("/api/debts/{debt_id}")
def get_debt_detail(debt_id: str):
    with get_conn() as conn:
        debt = conn.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()
        if debt is None:
            raise HTTPException(404, "not found")
        calls = conn.execute(
            "SELECT * FROM calls WHERE debt_id = ? ORDER BY started_at", (debt_id,)
        ).fetchall()
        sms = conn.execute(
            "SELECT * FROM sms_messages WHERE debt_id = ? ORDER BY sent_at", (debt_id,)
        ).fetchall()
        memory = conn.execute(
            "SELECT * FROM memory WHERE debt_id = ? ORDER BY learned_at", (debt_id,)
        ).fetchall()
        actions = conn.execute(
            "SELECT * FROM agent_actions WHERE debt_id = ? ORDER BY at", (debt_id,)
        ).fetchall()
    return {
        "debt": dict(debt),
        "calls": [dict(r) for r in calls],
        "sms_messages": [dict(r) for r in sms],
        "memory": [dict(r) for r in memory],
        "agent_actions": [dict(r) for r in actions],
    }


@router.post("/api/debts/{debt_id}/update")
def update_debt(debt_id: str, req: DebtUpdateRequest):
    """Edit an existing customer's per-cycle repayment terms. Only fields
    present in the request body are changed (sending null clears an override
    back to the policy default) - omitted fields keep whatever they were."""
    fields = req.model_dump(exclude_unset=True)
    _validate_repayment_terms(
        fields.get("due_now_percent"), fields.get("min_payment_today_percent"), fields.get("cycle_days")
    )
    column_map = {
        "due_now_percent": "due_now_percent_override",
        "min_payment_today_percent": "min_payment_today_percent_override",
        "cycle_days": "cycle_days_override",
    }
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM debts WHERE id = ?", (debt_id,)).fetchone()
        if existing is None:
            raise HTTPException(404, "not found")
        if fields:
            set_clause = ", ".join(f"{column_map[k]} = ?" for k in fields)
            conn.execute(f"UPDATE debts SET {set_clause} WHERE id = ?", (*fields.values(), debt_id))
        debt = conn.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()
    return dict(debt)


@router.get("/api/debts/{debt_id}/progress")
def get_debt_progress(debt_id: str):
    """Key measures for the person progress page (md/dashboard-spec.md)."""
    debt = agent_tools._debt_row(debt_id)
    if "error" in debt:
        raise HTTPException(404, "not found")
    with get_conn() as conn:
        calls_made = conn.execute(
            "SELECT COUNT(*) AS n FROM calls WHERE debt_id = ?", (debt_id,)
        ).fetchone()["n"]
        sms_links_sent = conn.execute(
            "SELECT COUNT(*) AS n FROM sms_messages WHERE debt_id = ? AND type = 'payment_link'", (debt_id,)
        ).fetchone()["n"]
    policy = agent_tools.effective_policy(debt, get_policy())
    schedule_info = offer_engine.payment_schedule(debt["amount_due"], debt["amount_collected"], policy, get_demo_now())
    return {
        "debt_id": debt_id,
        "amount_due": debt["amount_due"],
        "amount_collected": debt["amount_collected"],
        "amount_promised": debt["amount_promised"],
        "calls_made": calls_made,
        "sms_links_sent": sms_links_sent,
        "status": debt["status"],
        "next_action": debt["next_action"],
        "next_action_at": debt["next_action_at"],
        **schedule_info,
    }


@router.get("/api/debts/{debt_id}/memory")
def get_debt_memory(debt_id: str):
    return agent_tools.get_memory(debt_id)


@router.get("/api/debts/{debt_id}/calls")
def get_debt_calls(debt_id: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM calls WHERE debt_id = ? ORDER BY started_at", (debt_id,)
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/debts/{debt_id}/sms")
def get_debt_sms(debt_id: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sms_messages WHERE debt_id = ? ORDER BY sent_at", (debt_id,)
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/debts/{debt_id}/run-agent")
def run_agent(debt_id: str, force: bool = False):
    """Manual 'Run agent' button. Runs the deterministic simulator - the same
    engine the demo-clock scheduler fires - so a click here behaves exactly
    like a due scheduled action. The live a1mobile/realtime phone call is a
    separate, explicit path (server/routes/voice.py), not this endpoint."""
    debt = agent_tools.get_debt_profile(debt_id)
    if "error" in debt:
        raise HTTPException(404, "not found")
    if debt["status"] == "paid":
        raise HTTPException(400, "already paid")
    if debt["status"] == "needs_review" and not force:
        raise HTTPException(400, "needs_review - pass force=true to override")
    result = run_simulated_call(debt_id)
    return {"debt_id": debt_id, "result": result}


@router.post("/api/debts/{debt_id}/call-agent")
def call_agent(debt_id: str, background_tasks: BackgroundTasks):
    """Place a real outbound phone call through Vapi's a1mobile SIP trunk."""
    debt = agent_tools.get_debt_profile(debt_id)
    if "error" in debt:
        raise HTTPException(404, "not found")
    if debt["status"] == "paid":
        raise HTTPException(400, "already paid")
    if debt["status"] == "needs_review":
        raise HTTPException(400, "needs_review")
    result = place_call(debt["phone"], debt_id)
    if result.get("id"):
        background_tasks.add_task(poll_vapi_call_until_ended, result["id"])
    return {"debt_id": debt_id, "phone": debt["phone"], "result": result}


@router.post("/api/debts/{debt_id}/simulate-no-answer")
def simulate_no_answer(debt_id: str):
    debt = agent_tools.get_debt_profile(debt_id)
    if "error" in debt:
        raise HTTPException(404, "not found")
    agent_tools.record_call_event(debt_id, outcome="no_answer", summary="Borrower did not answer.")
    return agent_tools.update_debt_status(debt_id, status="no_answer", last_call_summary="No answer.")


@router.post("/api/debts/{debt_id}/simulate-promise")
def simulate_promise(debt_id: str, amount_today: float, amount_remainder: float = 0, promise_date: str | None = None):
    debt = agent_tools.get_debt_profile(debt_id)
    if "error" in debt:
        raise HTTPException(404, "not found")
    summary = f"Borrower agreed to pay ${amount_today:g} today" + (
        f" and ${amount_remainder:g} by {promise_date}." if amount_remainder > 0 else "."
    )
    agent_tools.record_call_event(
        debt_id,
        outcome="promised",
        summary=summary,
        amount_promised=amount_today + amount_remainder,
        promise_date=promise_date,
    )
    agent_tools.update_debt_status(debt_id, status="promised", last_call_summary=summary)
    return agent_tools.send_sms_payment_link(debt_id, amount=amount_today, reason="promised_today")


@router.get("/api/calls")
def list_calls():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM calls ORDER BY started_at DESC").fetchall()
    return [dict(r) for r in rows]
