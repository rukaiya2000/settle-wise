"""Read-only JSON API backing the demo dashboard (md/system-architecture.md)."""

from fastapi import APIRouter

from ..db import get_conn

router = APIRouter()


@router.get("/api/debts")
def list_debts():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM debts ORDER BY breach_date").fetchall()
    return [dict(r) for r in rows]


@router.get("/api/debts/{debt_id}")
def get_debt_detail(debt_id: str):
    with get_conn() as conn:
        debt = conn.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()
        if debt is None:
            return {"error": "not found"}
        calls = conn.execute(
            "SELECT * FROM calls WHERE debt_id = ? ORDER BY started_at", (debt_id,)
        ).fetchall()
        sms = conn.execute(
            "SELECT * FROM sms_messages WHERE debt_id = ? ORDER BY sent_at", (debt_id,)
        ).fetchall()
        memory = conn.execute(
            "SELECT * FROM memory WHERE debt_id = ? ORDER BY learned_at", (debt_id,)
        ).fetchall()
    return {
        "debt": dict(debt),
        "calls": [dict(r) for r in calls],
        "sms_messages": [dict(r) for r in sms],
        "memory": [dict(r) for r in memory],
    }


@router.get("/api/calls")
def list_calls():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM calls ORDER BY started_at DESC").fetchall()
    return [dict(r) for r in rows]
