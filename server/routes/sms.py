"""Send an SMS to a borrower from the dashboard.

A provider rejection (or no provider configured at all - see
server/sms_client.py) is surfaced to the person who clicked, not swallowed.
"""

import requests
from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from .. import sms_client
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
    except sms_client.SmsNotConfigured as e:
        raise HTTPException(503, str(e))
    except requests.HTTPError as e:
        detail = e.response.text if e.response is not None else str(e)
        logger.warning(f"SMS to {debt.get('phone')} rejected: {detail}")
        raise HTTPException(502, f"SMS provider rejected the message: {detail}")

    if "error" in result:
        raise HTTPException(400, result["error"])

    logger.info(f"[sms] {result['name']} {result['to']}: {result['body']}")
    return result
