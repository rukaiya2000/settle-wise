"""Mock payment checkout (md/system-architecture.md: fake /pay/:paymentId
that simulates success/pending states - no real payment processor)."""

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..db import get_conn

router = APIRouter()


def _find_sms(payment_id: str) -> dict | None:
    link_path = f"/pay/{payment_id}"
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sms_messages WHERE payment_link = ?", (link_path,)
        ).fetchone()
    return dict(row) if row else None


@router.get("/pay/{payment_id}", response_class=HTMLResponse)
def pay_page(payment_id: str):
    sms = _find_sms(payment_id)
    if not sms:
        raise HTTPException(404, "Unknown payment link")

    match = re.search(r"\$([0-9.]+)", sms["body"])
    amount = match.group(1) if match else "?"

    if sms["payment_status"] == "paid":
        return f"<h2>Already paid</h2><p>${amount} received. Thank you.</p>"

    return f"""
    <html><body style="font-family: sans-serif; max-width: 420px; margin: 60px auto;">
      <h2>SettleWise mock checkout</h2>
      <p>Amount due: <strong>${amount}</strong></p>
      <form method="post" action="/pay/{payment_id}/complete">
        <button type="submit" style="padding:10px 20px; font-size:16px;">Pay ${amount} now</button>
      </form>
    </body></html>
    """


@router.post("/pay/{payment_id}/complete")
def complete_payment(payment_id: str):
    sms = _find_sms(payment_id)
    if not sms:
        raise HTTPException(404, "Unknown payment link")
    with get_conn() as conn:
        conn.execute("UPDATE sms_messages SET payment_status = 'paid' WHERE id = ?", (sms["id"],))
        conn.execute(
            "UPDATE debts SET status = 'paid', next_action = 'None' WHERE id = ?",
            (sms["debt_id"],),
        )
    return {"payment_id": payment_id, "status": "paid"}
