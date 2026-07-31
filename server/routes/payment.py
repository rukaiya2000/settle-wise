"""Mock payment checkout (md/system-architecture.md: fake /pay/:paymentId
that simulates success/pending states - no real payment processor)."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..agent import tools as agent_tools
from ..db import get_conn

router = APIRouter()


def _find_sms_by_payment_id(payment_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sms_messages WHERE payment_id = ?", (payment_id,)).fetchone()
    return dict(row) if row else None


@router.get("/pay/{payment_id}", response_class=HTMLResponse)
def pay_page(payment_id: str):
    sms = _find_sms_by_payment_id(payment_id)
    if not sms:
        raise HTTPException(404, "Unknown payment link")

    amount = sms["amount"]

    if sms["payment_status"] == "paid":
        return f"<h2>Already paid</h2><p>${amount:g} received. Thank you.</p>"

    return f"""
    <html><body style="font-family: sans-serif; max-width: 420px; margin: 60px auto;">
      <h2>SettleWise mock checkout</h2>
      <p>Amount due: <strong>${amount:g}</strong></p>
      <form method="post" action="/pay/{payment_id}/complete">
        <button type="submit" style="padding:10px 20px; font-size:16px;">Pay ${amount:g} now</button>
      </form>
    </body></html>
    """


@router.post("/pay/{payment_id}/complete")
def complete_payment(payment_id: str):
    sms = _find_sms_by_payment_id(payment_id)
    if not sms:
        raise HTTPException(404, "Unknown payment link")
    debt = agent_tools.mark_paid(sms["debt_id"], sms["amount"], sms_id=sms["id"])
    return {"payment_id": payment_id, "status": "paid", "debt": debt}


@router.post("/api/payments/{payment_id}/mark-paid")
def mark_paid_api(payment_id: str):
    """Same completion as /pay/{payment_id}/complete, under the REST path
    named in md/technical-spec.md's Backend Endpoints."""
    return complete_payment(payment_id)
