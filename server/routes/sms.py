"""Send an SMS to a borrower from the dashboard.

a1mobile only delivers to numbers your team has OTP-verified (or organizer
test lines) - no cold outreach - so sending to an unverified number fails at
the provider. That error is surfaced rather than swallowed.
"""

import requests
from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from ..agent import tools as agent_tools

router = APIRouter()


class SmsRequest(BaseModel):
    body: str | None = None
    type: str = "custom"  # "custom" | "payment_link" | "reminder"
    amount: float | None = None


@router.post("/api/debts/{debt_id}/sms")
def send_sms(debt_id: str, req: SmsRequest):
    debt = agent_tools.get_debt_profile(debt_id)
    if "error" in debt:
        raise HTTPException(404, "not found")

    try:
        result = agent_tools.send_sms_now(
            debt_id, body=req.body, sms_type=req.type, amount=req.amount
        )
    except requests.HTTPError as e:
        detail = e.response.text if e.response is not None else str(e)
        logger.warning(f"SMS to {debt.get('phone')} rejected: {detail}")
        raise HTTPException(
            502,
            f"a1mobile rejected the message: {detail}. "
            "Numbers must be OTP-verified first "
            "(python -m server.a1mobile_client verify \"<number>\").",
        )

    if "error" in result:
        raise HTTPException(400, result["error"])

    logger.info(f"[sms] {result['name']} {result['to']}: {result['body']}")
    return result
