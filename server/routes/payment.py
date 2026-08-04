"""Mock payment checkout (md/system-architecture.md: fake /pay/:paymentId
that simulates success/pending states - no real payment processor).

Borrower-facing and reached from an SMS, so it is built mobile-first and
self-contained: no external CSS, no framework, works on a phone browser with
one tap. Paying posts to /complete, which updates the debt and SMS rows, then
the page swaps to a receipt without a reload.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..agent import tools as agent_tools
from ..db import get_conn
from .. import offer_engine
from ..policy import get_policy

router = APIRouter()

PAGE_CSS = """
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
       background:#f4f6f8;color:#1c2430;display:flex;align-items:center;
       justify-content:center;min-height:100vh;padding:20px}
  .card{background:#fff;border:1px solid #e2e6ea;border-radius:16px;padding:28px 24px;
        width:100%;max-width:400px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
  .brand{font-weight:700;font-size:18px;letter-spacing:-.02em;margin-bottom:2px}
  .sub{color:#6a747c;font-size:13px;margin-bottom:22px}
  .amount{font-size:40px;font-weight:700;letter-spacing:-.02em;line-height:1.1}
  .amount-label{font-size:12px;color:#6a747c;text-transform:uppercase;
                letter-spacing:.04em;margin-bottom:4px}
  .rows{border-top:1px solid #e2e6ea;margin:22px 0;padding-top:14px}
  .row{display:flex;justify-content:space-between;font-size:13px;padding:5px 0}
  .row span:first-child{color:#6a747c}
  button{width:100%;padding:14px;font-size:16px;font-weight:600;border:0;
         border-radius:10px;background:#12181f;color:#fff;cursor:pointer;
         font-family:inherit}
  button:hover{background:#2a3646}
  button:disabled{opacity:.6;cursor:default}
  .note{font-size:11px;color:#6a747c;text-align:center;margin-top:14px;line-height:1.5}
  .ok{text-align:center}
  .tick{width:56px;height:56px;border-radius:50%;background:#e6f6ec;color:#1f8a4c;
        font-size:30px;line-height:56px;margin:0 auto 14px}
  .ok h2{margin:0 0 6px;font-size:20px}
  .err{background:#fbeae8;color:#c33a32;border-radius:8px;padding:10px 12px;
       font-size:13px;margin-top:14px;display:none}
"""


def _find_sms_by_payment_id(payment_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sms_messages WHERE payment_id = ?", (payment_id,)).fetchone()
    return dict(row) if row else None


def _receipt(amount: float, name: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Payment received</title><style>{PAGE_CSS}</style></head><body>
  <div class="card ok">
    <div class="tick">&check;</div>
    <h2>Payment received</h2>
    <div class="sub">${amount:g} paid. Thank you, {name}.</div>
    <div class="rows"><div class="row"><span>Amount</span><span>${amount:g}</span></div>
    <div class="row"><span>Status</span><span>Paid</span></div></div>
    <div class="note">A confirmation has been added to your account.</div>
  </div></body></html>"""


@router.get("/pay/{payment_id}", response_class=HTMLResponse)
def pay_page(payment_id: str):
    sms = _find_sms_by_payment_id(payment_id)
    if not sms:
        raise HTTPException(404, "Unknown payment link")

    debt = agent_tools._debt_row(sms["debt_id"])
    name = debt.get("name", "") if "error" not in debt else ""
    amount = sms["amount"] or 0

    if sms["payment_status"] == "paid":
        return _receipt(amount, name)

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pay ${amount:g} - SettleWise</title><style>{PAGE_CSS}</style></head><body>
  <div class="card" id="card">
    <div class="brand">SettleWise</div>
    <div class="sub">Secure payment</div>

    <div class="amount-label">Amount due today</div>
    <div class="amount">${amount:g}</div>

    <div class="rows">
      <div class="row"><span>Account</span><span>{name}</span></div>
      <div class="row"><span>Reference</span><span>{payment_id}</span></div>
    </div>

    <button id="payBtn" onclick="pay()">Pay ${amount:g}</button>
    <div class="err" id="err"></div>
    <div class="note">This is a demo checkout. No real payment is taken and no
    card details are collected.</div>
  </div>

<script>
async function pay() {{
  const btn = document.getElementById('payBtn');
  const err = document.getElementById('err');
  btn.disabled = true; btn.textContent = 'Processing...'; err.style.display = 'none';
  try {{
    const res = await fetch('/pay/{payment_id}/complete', {{ method: 'POST' }});
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    const shortfall = data.shortfall_this_cycle || 0;
    // Swap to the receipt in place - a reload would lose the transition and
    // the borrower is on a phone. Built here (not reusing the server-rendered
    // receipt) because the shortfall is only known once payment completes.
    document.getElementById('card').outerHTML = `
      <div class="card ok">
        <div class="tick">&check;</div>
        <h2>Payment received</h2>
        <div class="sub">$${{data.amount_paid}} paid. Thank you, {name}.</div>
        <div class="rows">
          <div class="row"><span>Amount</span><span>$${{data.amount_paid}}</span></div>
          <div class="row"><span>Status</span><span>Paid</span></div>
          ${{shortfall > 0 ? `<div class="row"><span>Still due this cycle</span><span>$${{shortfall}}</span></div>` : ''}}
        </div>
        <div class="note">${{shortfall > 0 ? 'A reminder for the rest of this cycle will follow.' : 'A confirmation has been added to your account.'}}</div>
      </div>`;
  }} catch (e) {{
    btn.disabled = false; btn.textContent = 'Pay ${amount:g}';
    err.textContent = 'Payment failed: ' + e.message; err.style.display = 'block';
  }}
}}
</script></body></html>"""


@router.post("/pay/{payment_id}/complete")
def complete_payment(payment_id: str):
    sms = _find_sms_by_payment_id(payment_id)
    if not sms:
        raise HTTPException(404, "Unknown payment link")
    if sms["payment_status"] == "paid":
        # Tapping twice must not collect twice.
        return {"payment_id": payment_id, "status": "already_paid"}

    # What was actually due this cycle, computed BEFORE the payment lands -
    # if they paid the floor rather than the full due_now, the diff is what's
    # still short for this cycle. amount_collected already going up covers it
    # for *future* cycles automatically (due_now is a fresh % of whatever
    # remains); this is just making that gap visible at the moment it opens.
    debt_before = agent_tools._debt_row(sms["debt_id"])
    policy = agent_tools.effective_policy(debt_before, get_policy())
    due_now_before = offer_engine.payment_targets(
        debt_before["amount_due"], debt_before["amount_collected"], policy
    )["due_now"]
    amount_paid = sms["amount"] or 0
    shortfall = round(max(0.0, due_now_before - amount_paid), 2)

    debt = agent_tools.mark_paid(sms["debt_id"], amount_paid, sms_id=sms["id"])
    return {
        "payment_id": payment_id,
        "status": "paid",
        "debt": debt,
        "amount_paid": amount_paid,
        "cycle_due": due_now_before,
        "shortfall_this_cycle": shortfall,
    }


@router.post("/api/payments/{payment_id}/mark-paid")
def mark_paid_api(payment_id: str):
    """Same completion as /pay/{payment_id}/complete, under the REST path
    named in md/technical-spec.md's Backend Endpoints."""
    return complete_payment(payment_id)
